from __future__ import annotations

from arbitrage_bot.models import Opportunity, Ticker


def find_opportunities(
    exchange_tickers: dict[str, dict[str, Ticker]],
    symbols: list[str],
    fee_pct: float,
) -> list[Opportunity]:
    """Compares the same symbol across multiple exchanges.

    exchange_tickers: {exchange_id: {symbol: Ticker}}
    Needs at least 2 exchanges with data for a given symbol to find anything.
    """
    opportunities: list[Opportunity] = []

    for symbol in symbols:
        quotes = [
            (exchange_id, data[symbol])
            for exchange_id, data in exchange_tickers.items()
            if symbol in data
        ]
        if len(quotes) < 2:
            continue

        buy_exchange, buy_ticker = min(quotes, key=lambda q: q[1].ask)
        sell_exchange, sell_ticker = max(quotes, key=lambda q: q[1].bid)

        if buy_exchange == sell_exchange:
            continue

        gross_profit_pct = (sell_ticker.bid - buy_ticker.ask) / buy_ticker.ask
        net_profit_pct = gross_profit_pct - 2 * fee_pct

        if net_profit_pct > 0:
            opportunities.append(
                Opportunity(
                    kind="cross_exchange",
                    description=(
                        f"Comprar {symbol} em {buy_exchange} @ {buy_ticker.ask} / "
                        f"Vender em {sell_exchange} @ {sell_ticker.bid}"
                    ),
                    net_profit_pct=net_profit_pct,
                    gross_profit_pct=gross_profit_pct,
                    details={
                        "symbol": symbol,
                        "buy_exchange": buy_exchange,
                        "sell_exchange": sell_exchange,
                    },
                )
            )

    opportunities.sort(key=lambda o: o.net_profit_pct, reverse=True)
    return opportunities
