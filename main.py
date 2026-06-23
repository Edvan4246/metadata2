from __future__ import annotations

import argparse
import logging
import time
from dataclasses import replace
from itertools import permutations

from arbitrage_bot import depth_check
from arbitrage_bot.balances import ExchangeBalances
from arbitrage_bot.config import Settings
from arbitrage_bot.depth_check import CrossExchangeFill
from arbitrage_bot.detectors import cross_exchange, triangular
from arbitrage_bot.exchange_client import ExchangeClient
from arbitrage_bot.models import OrderBook, Opportunity
from arbitrage_bot.opportunity_log import OpportunityLogger
from arbitrage_bot.portfolio import PaperPortfolio
from arbitrage_bot.risk import RiskManager

logger = logging.getLogger(__name__)


def _triangular_symbols(base: str, alts: list[str]) -> list[str]:
    symbols = {f"{alt}/{base}" for alt in alts} | {f"{base}/{alt}" for alt in alts}
    for x, y in permutations(alts, 2):
        symbols.add(f"{x}/{y}")
        symbols.add(f"{y}/{x}")
    return sorted(symbols)


class ArbitrageBot:
    """Wires detectors, risk management and paper execution into a polling loop.

    Never places real orders: it only reads public market data via ccxt and
    simulates fills through PaperPortfolio, so a misconfiguration can lose
    virtual capital at worst, never real funds.
    """

    def __init__(self, settings: Settings):
        self.settings = settings
        self.triangular_symbols = (
            _triangular_symbols(settings.base_currency, settings.triangular.alt_currencies)
            if settings.triangular.enabled
            else []
        )

        exchange_ids = sorted(set(settings.cross_exchange.exchanges) | {settings.exchange_id})
        self.clients = {eid: ExchangeClient(eid) for eid in exchange_ids}

        self.risk_manager = RiskManager(
            initial_capital=settings.risk.initial_capital,
            max_trade_pct=settings.risk.max_trade_pct,
            min_profit_pct=settings.risk.min_profit_pct,
            max_daily_loss_pct=settings.risk.max_daily_loss_pct,
        )
        self.portfolio = PaperPortfolio(self.risk_manager, settings.logging.trades_log_path)
        self.opportunity_logger = OpportunityLogger(settings.logging.opportunities_log_path)

        self.exchange_balances = (
            ExchangeBalances.from_allocation(settings.cross_exchange.allocation)
            if settings.cross_exchange.enabled and settings.cross_exchange.allocation
            else None
        )

    def _symbols_for(self, exchange_id: str) -> list[str]:
        symbols: set[str] = set()
        if self.settings.triangular.enabled and exchange_id == self.settings.exchange_id:
            symbols |= set(self.triangular_symbols)
        if self.settings.cross_exchange.enabled and exchange_id in self.settings.cross_exchange.exchanges:
            symbols |= set(self.settings.cross_exchange.symbols)
        return sorted(symbols)

    def run_iteration(self) -> None:
        if self.risk_manager.trading_halted:
            logger.warning("Circuit breaker ativo: pulando iteracao (sem novas operacoes hoje).")
            return

        tickers_by_exchange = {
            eid: client.fetch_tickers(self._symbols_for(eid)) for eid, client in self.clients.items()
        }

        opportunities = []
        if self.settings.triangular.enabled:
            primary_tickers = tickers_by_exchange.get(self.settings.exchange_id, {})
            opportunities += triangular.find_opportunities(
                primary_tickers,
                self.settings.base_currency,
                self.settings.triangular.alt_currencies,
                self.settings.risk.taker_fee_pct,
            )
        if self.settings.cross_exchange.enabled:
            cross_tickers = {
                eid: tickers_by_exchange[eid] for eid in self.settings.cross_exchange.exchanges
            }
            opportunities += cross_exchange.find_opportunities(
                cross_tickers,
                self.settings.cross_exchange.symbols,
                self.settings.risk.taker_fee_pct,
            )

        self.opportunity_logger.log(opportunities)

        for opp in opportunities:
            trade_size_quote = self.risk_manager.capital * self.risk_manager.max_trade_pct
            if trade_size_quote <= 0:
                continue

            if opp.kind == "cross_exchange":
                trade_size_quote = self._cap_by_inventory(opp, trade_size_quote)
                if trade_size_quote <= 0:
                    logger.debug(
                        "Sem capital pre-posicionado suficiente nas exchanges para: %s", opp.description
                    )
                    continue

            # The ticker scan above only sees the best bid/ask, not how much
            # volume actually sits there. Re-check the real order book for the
            # exact size we'd trade before trusting the opportunity.
            validation = self._validate_with_depth(opp, trade_size_quote)
            if validation is None:
                logger.debug("Profundidade insuficiente para validar: %s", opp.description)
                continue
            realistic_net_profit_pct, fill = validation

            validated_opp = replace(opp, net_profit_pct=realistic_net_profit_pct)
            trade_size = self.risk_manager.evaluate(validated_opp, candidate_trade_size=trade_size_quote)
            if trade_size is None:
                continue
            trade = self.portfolio.execute(validated_opp, trade_size)

            if opp.kind == "cross_exchange" and self.exchange_balances is not None and fill is not None:
                self.exchange_balances.settle_cross_exchange_trade(
                    opp.details["buy_exchange"],
                    opp.details["sell_exchange"],
                    opp.details["symbol"],
                    quote_spent=trade_size,
                    base_bought=fill.base_amount,
                    quote_received=fill.quote_received,
                )
                for warning in self.exchange_balances.skew_warnings(self.settings.cross_exchange.rebalance_warning_pct):
                    logger.warning(warning)

            logger.info(
                "Trade simulado [%s]: %s | lucro liquido (validado no livro) %.4f%% | capital apos: %.2f",
                trade.kind,
                trade.description,
                trade.pnl_pct * 100,
                trade.capital_after,
            )

    def _cap_by_inventory(self, opp: Opportunity, trade_size_quote: float) -> float:
        if self.exchange_balances is None:
            return trade_size_quote
        max_size = self.exchange_balances.max_cross_exchange_quote_size(
            opp.details["buy_exchange"],
            opp.details["sell_exchange"],
            opp.details["symbol"],
            opp.details["sell_price"],
        )
        return min(trade_size_quote, max_size)

    def _validate_with_depth(
        self, opp: Opportunity, trade_size_quote: float
    ) -> tuple[float, CrossExchangeFill | None] | None:
        if opp.kind == "cross_exchange":
            symbol = opp.details["symbol"]
            buy_client = self.clients[opp.details["buy_exchange"]]
            sell_client = self.clients[opp.details["sell_exchange"]]
            buy_book = buy_client.fetch_order_book(symbol)
            sell_book = sell_client.fetch_order_book(symbol)
            if buy_book is None or sell_book is None:
                return None
            fill = depth_check.validate_cross_exchange(
                buy_book, sell_book, trade_size_quote, self.settings.risk.taker_fee_pct
            )
            if fill is None:
                return None
            return fill.net_profit_pct, fill

        if opp.kind == "triangular":
            base, x, y = opp.details["base"], opp.details["x"], opp.details["y"]
            client = self.clients[self.settings.exchange_id]
            symbols = set()
            for a, b in ((base, x), (x, y), (y, base)):
                symbols.add(f"{a}/{b}")
                symbols.add(f"{b}/{a}")

            books: dict[str, OrderBook] = {}
            for symbol in symbols:
                book = client.fetch_order_book(symbol)
                if book is not None:
                    books[symbol] = book

            net_profit_pct = depth_check.validate_triangular(
                base, x, y, trade_size_quote, books, self.settings.risk.taker_fee_pct
            )
            if net_profit_pct is None:
                return None
            return net_profit_pct, None

        return None

    def run(self, once: bool = False, max_iterations: int | None = None) -> None:
        iteration = 0
        while True:
            iteration += 1
            try:
                self.run_iteration()
            except Exception:
                logger.exception("Erro na iteracao do loop; continuando na proxima.")

            if once or (max_iterations is not None and iteration >= max_iterations):
                break
            time.sleep(self.settings.interval_seconds)


def main() -> None:
    parser = argparse.ArgumentParser(description="Bot de arbitragem cripto (paper trading)")
    parser.add_argument("--config", default="config/settings.yaml", help="Caminho do arquivo de configuracao")
    parser.add_argument("--once", action="store_true", help="Executa uma unica iteracao e sai")
    parser.add_argument("--max-iterations", type=int, default=None, help="Numero maximo de iteracoes")
    args = parser.parse_args()

    settings = Settings.load(args.config)
    logging.basicConfig(
        level=getattr(logging, settings.logging.level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    logger.info(
        "Iniciando bot em modo PAPER TRADING (sem dinheiro real). Capital virtual: %.2f %s",
        settings.risk.initial_capital,
        settings.base_currency,
    )

    bot = ArbitrageBot(settings)
    try:
        bot.run(once=args.once, max_iterations=args.max_iterations)
    except KeyboardInterrupt:
        logger.info("Interrompido pelo usuario. Capital final: %.2f", bot.risk_manager.capital)


if __name__ == "__main__":
    main()
