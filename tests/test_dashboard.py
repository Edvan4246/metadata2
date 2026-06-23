from __future__ import annotations

import csv

from dashboard import create_app
from arbitrage_bot.config import Settings

SAMPLE_YAML = """
exchange:
  id: binance

base_currency: USDT

triangular:
  enabled: true
  alt_currencies: [BTC]

cross_exchange:
  enabled: false
  exchanges: [binance]
  symbols: []

risk:
  initial_capital: 1000.0
  max_trade_pct: 0.02
  min_profit_pct: 0.003
  max_daily_loss_pct: 0.05
  taker_fee_pct: 0.001

loop:
  interval_seconds: 10

logging:
  level: INFO
  trades_log_path: {trades_path}
  opportunities_log_path: {opportunities_path}
"""


def _settings(tmp_path):
    trades_path = tmp_path / "trades.csv"
    opportunities_path = tmp_path / "opportunities.csv"
    with trades_path.open("w", newline="") as f:
        writer = csv.DictWriter(
            f, fieldnames=["timestamp", "kind", "description", "trade_size_base", "pnl_base", "pnl_pct", "capital_after"]
        )
        writer.writeheader()
        writer.writerow(
            {
                "timestamp": "2024-01-01T00:00:00+00:00",
                "kind": "cross_exchange",
                "description": "test",
                "trade_size_base": "10.0",
                "pnl_base": "1.0",
                "pnl_pct": "0.1",
                "capital_after": "1001.0",
            }
        )

    config_path = tmp_path / "settings.yaml"
    config_path.write_text(
        SAMPLE_YAML.format(trades_path=trades_path, opportunities_path=opportunities_path)
    )
    return Settings.load(config_path)


def test_index_page_renders(tmp_path):
    app = create_app(_settings(tmp_path))
    client = app.test_client()

    response = client.get("/")

    assert response.status_code == 200
    assert b"Dashboard" in response.data


def test_api_summary_reflects_logged_trades(tmp_path):
    app = create_app(_settings(tmp_path))
    client = app.test_client()

    response = client.get("/api/summary")

    assert response.status_code == 200
    body = response.get_json()
    assert body["total_trades"] == 1
    assert body["current_capital"] == 1001.0


def test_api_opportunities_empty_when_no_log_yet(tmp_path):
    app = create_app(_settings(tmp_path))
    client = app.test_client()

    response = client.get("/api/opportunities")

    assert response.status_code == 200
    assert response.get_json() == []
