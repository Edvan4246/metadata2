from __future__ import annotations

import csv

from arbitrage_bot.dashboard_data import load_opportunities, load_trades, summarize_trades

_TRADE_FIELDS = ["timestamp", "kind", "description", "trade_size_base", "pnl_base", "pnl_pct", "capital_after"]
_OPP_FIELDS = ["timestamp", "kind", "description", "gross_profit_pct", "net_profit_pct"]


def _write_csv(path, fields, rows):
    with path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def test_load_trades_missing_file_returns_empty(tmp_path):
    assert load_trades(tmp_path / "missing.csv") == []


def test_load_trades_parses_numeric_fields(tmp_path):
    path = tmp_path / "trades.csv"
    _write_csv(
        path,
        _TRADE_FIELDS,
        [
            {
                "timestamp": "2024-01-01T00:00:00+00:00",
                "kind": "cross_exchange",
                "description": "x",
                "trade_size_base": "20.0",
                "pnl_base": "0.2",
                "pnl_pct": "0.01",
                "capital_after": "1000.2",
            }
        ],
    )

    trades = load_trades(path)

    assert trades == [
        {
            "timestamp": "2024-01-01T00:00:00+00:00",
            "kind": "cross_exchange",
            "description": "x",
            "trade_size_base": 20.0,
            "pnl_base": 0.2,
            "pnl_pct": 0.01,
            "capital_after": 1000.2,
        }
    ]


def test_load_opportunities_missing_file_returns_empty(tmp_path):
    assert load_opportunities(tmp_path / "missing.csv") == []


def test_summarize_trades_empty():
    summary = summarize_trades([])
    assert summary["total_trades"] == 0
    assert summary["win_rate"] is None
    assert summary["current_capital"] is None
    assert summary["capital_curve"] == []


def test_summarize_trades_computes_win_rate_and_by_kind():
    trades = [
        {"timestamp": "t1", "kind": "cross_exchange", "description": "a", "trade_size_base": 10.0,
         "pnl_base": 1.0, "pnl_pct": 0.1, "capital_after": 1001.0},
        {"timestamp": "t2", "kind": "triangular", "description": "b", "trade_size_base": 10.0,
         "pnl_base": -0.5, "pnl_pct": -0.05, "capital_after": 1000.5},
        {"timestamp": "t3", "kind": "cross_exchange", "description": "c", "trade_size_base": 10.0,
         "pnl_base": 2.0, "pnl_pct": 0.2, "capital_after": 1002.5},
    ]

    summary = summarize_trades(trades)

    assert summary["total_trades"] == 3
    assert summary["total_pnl_base"] == 2.5
    assert summary["win_rate"] == 2 / 3
    assert summary["current_capital"] == 1002.5
    assert summary["by_kind"]["cross_exchange"] == {"count": 2, "pnl_base": 3.0}
    assert summary["by_kind"]["triangular"] == {"count": 1, "pnl_base": -0.5}
    assert len(summary["capital_curve"]) == 3
