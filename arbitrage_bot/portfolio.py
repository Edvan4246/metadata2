from __future__ import annotations

import csv
import logging
from datetime import datetime, timezone
from pathlib import Path

from arbitrage_bot.models import Opportunity, Trade
from arbitrage_bot.risk import RiskManager

logger = logging.getLogger(__name__)

_TRADE_FIELDS = [
    "timestamp",
    "kind",
    "description",
    "trade_size_base",
    "pnl_base",
    "pnl_pct",
    "capital_after",
]


class PaperPortfolio:
    """Simulates trade execution without touching real funds or real exchange APIs."""

    def __init__(self, risk_manager: RiskManager, trades_log_path: str):
        self.risk_manager = risk_manager
        self.trades_log_path = Path(trades_log_path)
        self.trades_log_path.parent.mkdir(parents=True, exist_ok=True)
        if not self.trades_log_path.exists():
            with self.trades_log_path.open("w", newline="") as f:
                csv.DictWriter(f, fieldnames=_TRADE_FIELDS).writeheader()

    def execute(self, opportunity: Opportunity, trade_size_base: float) -> Trade:
        pnl_base = trade_size_base * opportunity.net_profit_pct
        self.risk_manager.record_pnl(pnl_base)

        trade = Trade(
            timestamp=datetime.now(timezone.utc),
            kind=opportunity.kind,
            description=opportunity.description,
            trade_size_base=trade_size_base,
            pnl_base=pnl_base,
            pnl_pct=opportunity.net_profit_pct,
            capital_after=self.risk_manager.capital,
        )
        self._append_log(trade)
        return trade

    def _append_log(self, trade: Trade) -> None:
        with self.trades_log_path.open("a", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=_TRADE_FIELDS)
            writer.writerow(
                {
                    "timestamp": trade.timestamp.isoformat(),
                    "kind": trade.kind,
                    "description": trade.description,
                    "trade_size_base": f"{trade.trade_size_base:.8f}",
                    "pnl_base": f"{trade.pnl_base:.8f}",
                    "pnl_pct": f"{trade.pnl_pct:.6f}",
                    "capital_after": f"{trade.capital_after:.8f}",
                }
            )
