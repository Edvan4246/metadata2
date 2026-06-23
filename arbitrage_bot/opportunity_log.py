from __future__ import annotations

import csv
from pathlib import Path

from arbitrage_bot.models import Opportunity

_FIELDS = ["timestamp", "kind", "description", "gross_profit_pct", "net_profit_pct"]


class OpportunityLogger:
    """Appends every detected opportunity to a CSV, even ones the risk manager rejects."""

    def __init__(self, path: str):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            with self.path.open("w", newline="") as f:
                csv.DictWriter(f, fieldnames=_FIELDS).writeheader()

    def log(self, opportunities: list[Opportunity]) -> None:
        if not opportunities:
            return
        with self.path.open("a", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=_FIELDS)
            for opp in opportunities:
                writer.writerow(
                    {
                        "timestamp": opp.timestamp.isoformat(),
                        "kind": opp.kind,
                        "description": opp.description,
                        "gross_profit_pct": f"{opp.gross_profit_pct:.6f}",
                        "net_profit_pct": f"{opp.net_profit_pct:.6f}",
                    }
                )
