from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass
class Ticker:
    bid: float
    ask: float


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
