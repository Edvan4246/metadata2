from __future__ import annotations

from arbitrage_bot.config import Settings

SAMPLE_YAML = """
exchange:
  id: binance

base_currency: USDT

triangular:
  enabled: true
  alt_currencies: [BTC, ETH]

cross_exchange:
  enabled: true
  exchanges: [binance, kraken]
  symbols: [BTC/USDT, ETH/USDT]
  allocation:
    binance:
      USDT: 100.0
      BTC: 0.01
  rebalance_warning_pct: 0.4

risk:
  initial_capital: 500.0
  max_trade_pct: 0.01
  min_profit_pct: 0.002
  max_daily_loss_pct: 0.04
  taker_fee_pct: 0.001

loop:
  interval_seconds: 10

logging:
  level: INFO
  trades_log_path: data/trades.csv
  opportunities_log_path: data/opportunities.csv
"""


def test_settings_load(tmp_path):
    config_path = tmp_path / "settings.yaml"
    config_path.write_text(SAMPLE_YAML)

    settings = Settings.load(config_path)

    assert settings.exchange_id == "binance"
    assert settings.base_currency == "USDT"
    assert settings.triangular.alt_currencies == ["BTC", "ETH"]
    assert settings.cross_exchange.exchanges == ["binance", "kraken"]
    assert settings.cross_exchange.allocation == {"binance": {"USDT": 100.0, "BTC": 0.01}}
    assert settings.cross_exchange.rebalance_warning_pct == 0.4
    assert settings.risk.initial_capital == 500.0
    assert settings.interval_seconds == 10
    assert settings.logging.level == "INFO"
