from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass

import ccxt

logger = logging.getLogger(__name__)

LIVE_CONFIRM_ENV_VAR = "ARBITRAGE_BOT_LIVE_CONFIRM"
LIVE_CONFIRM_VALUE = "I_UNDERSTAND_THE_RISK"


class LiveExecutionError(Exception):
    """Raised whenever a real order can't be confirmed as placed/filled as expected.

    Callers must never blindly retry order creation on this error: a network
    error here is ambiguous (the order may or may not have reached the
    exchange), and retrying risks sending the same order twice.
    """


def is_live_trading_enabled(config_enabled: bool, cli_flag: bool) -> bool:
    """Live order placement requires three independent gates to all be true:

    1. `live.enabled: true` in the config file (a deliberate, reviewed setting).
    2. The `--live` CLI flag (a deliberate choice at every invocation).
    3. The `ARBITRAGE_BOT_LIVE_CONFIRM` env var set to an exact confirmation
       string (so it can't be enabled accidentally by a stray `true` in the
       environment).

    Any single gate left off keeps the bot in paper trading.
    """
    env_confirmed = os.environ.get(LIVE_CONFIRM_ENV_VAR) == LIVE_CONFIRM_VALUE
    return bool(config_enabled and cli_flag and env_confirmed)


def load_credentials(exchange_id: str) -> tuple[str, str]:
    """Reads `{EXCHANGE_ID}_API_KEY` / `{EXCHANGE_ID}_API_SECRET` from the
    environment. Never reads keys from config files, so they can't end up
    committed to the repo by accident."""
    prefix = exchange_id.upper()
    api_key = os.environ.get(f"{prefix}_API_KEY")
    api_secret = os.environ.get(f"{prefix}_API_SECRET")
    if not api_key or not api_secret:
        raise LiveExecutionError(
            f"Credenciais ausentes para '{exchange_id}': defina "
            f"{prefix}_API_KEY e {prefix}_API_SECRET no ambiente."
        )
    return api_key, api_secret


class AuthenticatedExchangeClient:
    """ccxt wrapper that can place and track real orders.

    Distinct from `ExchangeClient` (read-only, public data) on purpose: an
    object capable of spending real money should never be reachable from
    code paths that only meant to read tickers/order books.
    """

    def __init__(self, exchange_id: str, api_key: str, api_secret: str):
        self.exchange_id = exchange_id
        exchange_class = getattr(ccxt, exchange_id)
        self.exchange = exchange_class(
            {"apiKey": api_key, "secret": api_secret, "enableRateLimit": True}
        )
        self.exchange.load_markets()

    def create_market_order(self, symbol: str, side: str, amount: float) -> dict:
        """Places a real market order. Does not retry: an exception here may
        mean the order never reached the exchange, or that it did and only the
        confirmation was lost -- retrying blindly risks a double fill."""
        try:
            return self.exchange.create_order(symbol, "market", side, amount)
        except ccxt.InsufficientFunds as exc:
            raise LiveExecutionError(f"Saldo insuficiente para {side} {amount} {symbol}: {exc}") from exc
        except ccxt.InvalidOrder as exc:
            raise LiveExecutionError(f"Ordem invalida para {side} {amount} {symbol}: {exc}") from exc
        except ccxt.NetworkError as exc:
            raise LiveExecutionError(
                f"Erro de rede ao enviar ordem {side} {amount} {symbol} -- "
                "estado da ordem incerto, verifique manualmente antes de tentar de novo: "
                f"{exc}"
            ) from exc
        except ccxt.ExchangeError as exc:
            raise LiveExecutionError(f"Exchange rejeitou ordem {side} {amount} {symbol}: {exc}") from exc

    def fetch_order(self, order_id: str, symbol: str) -> dict:
        try:
            return self.exchange.fetch_order(order_id, symbol)
        except ccxt.NetworkError as exc:
            raise LiveExecutionError(f"Erro de rede ao consultar ordem {order_id}: {exc}") from exc
        except ccxt.ExchangeError as exc:
            raise LiveExecutionError(f"Erro ao consultar ordem {order_id}: {exc}") from exc

    def wait_for_fill(self, order_id: str, symbol: str, timeout_seconds: float, poll_interval: float = 1.0) -> dict:
        """Polls order status (read-only, safe to retry) until it's no longer
        open or the timeout elapses. Returns the last known order state."""
        deadline = time.monotonic() + timeout_seconds
        order = self.fetch_order(order_id, symbol)
        while order.get("status") == "open" and time.monotonic() < deadline:
            time.sleep(poll_interval)
            order = self.fetch_order(order_id, symbol)
        return order


@dataclass
class CrossExchangeExecutionResult:
    base_amount_bought: float
    quote_spent: float
    base_amount_sold: float
    quote_received: float
    fully_hedged: bool  # False if we ended up holding unsold base inventory


class LiveCrossExchangeExecutor:
    """Executes a real two-legged cross-exchange trade: buy on one exchange,
    sell on another. Always sells exactly what was actually bought (never the
    originally intended amount), so a partial fill on the buy leg can never
    cause an oversell on the sell leg."""

    def __init__(self, clients: dict[str, AuthenticatedExchangeClient], order_timeout_seconds: float = 10.0):
        self.clients = clients
        self.order_timeout_seconds = order_timeout_seconds

    def execute(
        self,
        buy_exchange: str,
        sell_exchange: str,
        symbol: str,
        base_amount: float,
    ) -> CrossExchangeExecutionResult:
        buy_client = self.clients[buy_exchange]
        sell_client = self.clients[sell_exchange]

        buy_order = buy_client.create_market_order(symbol, "buy", base_amount)
        buy_order = buy_client.wait_for_fill(buy_order["id"], symbol, self.order_timeout_seconds)

        base_bought = float(buy_order.get("filled") or 0.0)
        quote_spent = float(buy_order.get("cost") or 0.0)

        if base_bought <= 0:
            raise LiveExecutionError(
                f"Perna de compra de {symbol} em {buy_exchange} nao preencheu nada "
                f"(status={buy_order.get('status')}); nenhuma venda foi enviada."
            )

        sell_order = sell_client.create_market_order(symbol, "sell", base_bought)
        sell_order = sell_client.wait_for_fill(sell_order["id"], symbol, self.order_timeout_seconds)

        base_sold = float(sell_order.get("filled") or 0.0)
        quote_received = float(sell_order.get("cost") or 0.0)
        fully_hedged = base_sold >= base_bought * (1 - 1e-9)

        if not fully_hedged:
            logger.warning(
                "Perna de venda de %s em %s preencheu so %.8f de %.8f comprado -- "
                "exposicao nao hedgeada de %.8f, intervencao manual pode ser necessaria.",
                symbol,
                sell_exchange,
                base_sold,
                base_bought,
                base_bought - base_sold,
            )

        return CrossExchangeExecutionResult(
            base_amount_bought=base_bought,
            quote_spent=quote_spent,
            base_amount_sold=base_sold,
            quote_received=quote_received,
            fully_hedged=fully_hedged,
        )
