from __future__ import annotations

import csv
from pathlib import Path


def _read_csv(path: str | Path) -> list[dict]:
    p = Path(path)
    if not p.exists():
        return []
    with p.open(newline="") as f:
        return list(csv.DictReader(f))


def load_trades(path: str | Path) -> list[dict]:
    """Reads the trades CSV log and converts numeric columns to floats.

    Returns rows oldest-first, matching the order they were appended to the
    log -- both PaperPortfolio and LivePortfolio append in execution order.
    """
    rows = _read_csv(path)
    trades = []
    for row in rows:
        trades.append(
            {
                "timestamp": row["timestamp"],
                "kind": row["kind"],
                "description": row["description"],
                "trade_size_base": float(row["trade_size_base"]),
                "pnl_base": float(row["pnl_base"]),
                "pnl_pct": float(row["pnl_pct"]),
                "capital_after": float(row["capital_after"]),
            }
        )
    return trades


def load_opportunities(path: str | Path) -> list[dict]:
    rows = _read_csv(path)
    opportunities = []
    for row in rows:
        opportunities.append(
            {
                "timestamp": row["timestamp"],
                "kind": row["kind"],
                "description": row["description"],
                "gross_profit_pct": float(row["gross_profit_pct"]),
                "net_profit_pct": float(row["net_profit_pct"]),
            }
        )
    return opportunities


def summarize_trades(trades: list[dict]) -> dict:
    """Aggregates the trade log into the figures a monitoring dashboard cares
    about: capital curve over time, win rate, and pnl broken down by
    arbitrage kind (triangular vs cross_exchange)."""
    if not trades:
        return {
            "total_trades": 0,
            "total_pnl_base": 0.0,
            "win_rate": None,
            "current_capital": None,
            "capital_curve": [],
            "by_kind": {},
        }

    total_pnl_base = sum(t["pnl_base"] for t in trades)
    wins = sum(1 for t in trades if t["pnl_base"] > 0)

    by_kind: dict[str, dict] = {}
    for t in trades:
        bucket = by_kind.setdefault(t["kind"], {"count": 0, "pnl_base": 0.0})
        bucket["count"] += 1
        bucket["pnl_base"] += t["pnl_base"]

    return {
        "total_trades": len(trades),
        "total_pnl_base": total_pnl_base,
        "win_rate": wins / len(trades),
        "current_capital": trades[-1]["capital_after"],
        "capital_curve": [{"timestamp": t["timestamp"], "capital_after": t["capital_after"]} for t in trades],
        "by_kind": by_kind,
    }
