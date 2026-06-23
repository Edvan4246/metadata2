from __future__ import annotations

import logging

import ccxt

from arbitrage_bot.models import OrderBook, Ticker

logger = logging.getLogger(__name__)


class ExchangeClient:
    """Thin wrapper around ccxt for read-only public market data.

    No API key/secret is required: paper trading only ever reads public
    order book / ticker data, it never places real orders.
    """

    def __init__(self, exchange_id: str):
        self.exchange_id = exchange_id
        exchange_class = getattr(ccxt, exchange_id)
        self.exchange = exchange_class({"enableRateLimit": True})
        self.exchange.load_markets()

    def has_symbol(self, symbol: str) -> bool:
        return symbol in self.exchange.markets

    def fetch_tickers(self, symbols: list[str]) -> dict[str, Ticker]:
        symbols = [s for s in symbols if self.has_symbol(s)]
        if not symbols:
            return {}
        raw = self.exchange.fetch_tickers(symbols)
        result = {}
        for symbol, t in raw.items():
            bid, ask = t.get("bid"), t.get("ask")
            if bid is None or ask is None:
                continue
            result[symbol] = Ticker(bid=bid, ask=ask)
        return result

    def fetch_order_book(self, symbol: str, depth: int = 20) -> OrderBook | None:
        """Fetches real depth for a single symbol, used to validate a candidate
        opportunity before committing to it (the cheap ticker scan only sees the
        best bid/ask, not how much volume is actually available there)."""
        if not self.has_symbol(symbol):
            return None
        raw = self.exchange.fetch_order_book(symbol, limit=depth)
        asks = [(price, amount) for price, amount, *_ in raw.get("asks", [])]
        bids = [(price, amount) for price, amount, *_ in raw.get("bids", [])]
        if not asks or not bids:
            return None
        return OrderBook(asks=asks, bids=bids)
