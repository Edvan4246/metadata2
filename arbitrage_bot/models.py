from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass
class Ticker:
    bid: float
    ask: float


@dataclass
class OrderBook:
    """A depth snapshot, used to simulate a realistic market-order fill instead
    of assuming the whole trade clears at the best bid/ask."""

    asks: list[tuple[float, float]]  # (price, base_amount), sorted lowest price first
    bids: list[tuple[float, float]]  # (price, base_amount), sorted highest price first

    def fill_buy(self, quote_amount: float) -> tuple[float, float] | None:
        """Spend `quote_amount` of quote currency walking the ask side.

        Returns (base_amount_bought, avg_price), or None if the book doesn't
        have enough depth to absorb the full amount.
        """
        result = _walk_book(self.asks, quote_amount, by="quote")
        if result is None:
            return None
        base_filled, quote_filled = result
        return base_filled, quote_filled / base_filled

    def fill_sell(self, base_amount: float) -> tuple[float, float] | None:
        """Sell `base_amount` of base currency walking the bid side.

        Returns (quote_amount_received, avg_price), or None if the book
        doesn't have enough depth to absorb the full amount.
        """
        result = _walk_book(self.bids, base_amount, by="base")
        if result is None:
            return None
        base_filled, quote_filled = result
        return quote_filled, quote_filled / base_filled


def _walk_book(levels: list[tuple[float, float]], amount: float, by: str) -> tuple[float, float] | None:
    remaining = amount
    base_filled = 0.0
    quote_filled = 0.0
    for price, volume in levels:
        if by == "quote":
            take_quote = min(remaining, price * volume)
            take_base = take_quote / price
        else:
            take_base = min(remaining, volume)
            take_quote = take_base * price
        base_filled += take_base
        quote_filled += take_quote
        remaining -= take_quote if by == "quote" else take_base
        if remaining <= amount * 1e-9:
            break
    if remaining > amount * 1e-6:
        return None
    return base_filled, quote_filled


@dataclass
class Opportunity:
    kind: str  # "triangular" or "cross_exchange"
    description: str
    net_profit_pct: float
    gross_profit_pct: float
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    details: dict = field(default_factory=dict)


@dataclass
class Trade:
    timestamp: datetime
    kind: str
    description: str
    trade_size_base: float
    pnl_base: float
    pnl_pct: float
    capital_after: float
