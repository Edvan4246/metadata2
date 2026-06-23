from __future__ import annotations

import pytest

from arbitrage_bot.balances import ExchangeBalances


def _balances() -> ExchangeBalances:
    return ExchangeBalances.from_allocation(
        {
            "binance": {"USDT": 1000.0, "BTC": 0.05},
            "kraken": {"USDT": 1000.0, "BTC": 0.05},
        }
    )


def test_max_cross_exchange_quote_size_capped_by_buy_side_quote():
    balances = ExchangeBalances.from_allocation(
        {
            "binance": {"USDT": 100.0, "BTC": 10.0},
            "kraken": {"USDT": 1000.0, "BTC": 10.0},
        }
    )
    max_size = balances.max_cross_exchange_quote_size("binance", "kraken", "BTC/USDT", sell_price_estimate=20000.0)
    assert max_size == 100.0


def test_max_cross_exchange_quote_size_capped_by_sell_side_base():
    balances = ExchangeBalances.from_allocation(
        {
            "binance": {"USDT": 10000.0, "BTC": 10.0},
            "kraken": {"USDT": 1000.0, "BTC": 0.01},
        }
    )
    max_size = balances.max_cross_exchange_quote_size("binance", "kraken", "BTC/USDT", sell_price_estimate=20000.0)
    assert max_size == pytest.approx(0.01 * 20000.0)


def test_settle_cross_exchange_trade_shifts_inventory():
    balances = _balances()
    balances.settle_cross_exchange_trade(
        "binance", "kraken", "BTC/USDT", quote_spent=200.0, base_bought=0.01, quote_received=205.0
    )

    assert balances.available("binance", "USDT") == 800.0
    assert balances.available("binance", "BTC") == pytest.approx(0.06)
    assert balances.available("kraken", "BTC") == pytest.approx(0.04)
    assert balances.available("kraken", "USDT") == pytest.approx(1205.0)


def test_skew_warning_triggers_below_threshold():
    balances = _balances()
    balances.settle_cross_exchange_trade(
        "kraken", "binance", "BTC/USDT", quote_spent=0.0, base_bought=0.0, quote_received=0.0
    )
    # drain kraken's BTC well below 50% of its 0.05 target
    balances.balances["kraken"]["BTC"] = 0.01

    warnings = balances.skew_warnings(warning_pct=0.5)

    assert any("kraken" in w and "BTC" in w for w in warnings)


def test_no_skew_warning_when_balanced():
    balances = _balances()
    assert balances.skew_warnings(warning_pct=0.5) == []
