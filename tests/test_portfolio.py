from __future__ import annotations

import csv

import pytest

from arbitrage_bot.models import Opportunity
from arbitrage_bot.portfolio import LivePortfolio, PaperPortfolio
from arbitrage_bot.risk import RiskManager


def test_execute_updates_capital_and_writes_log(tmp_path):
    rm = RiskManager(
        initial_capital=1000.0,
        max_trade_pct=0.02,
        min_profit_pct=0.003,
        max_daily_loss_pct=0.05,
    )
    log_path = tmp_path / "trades.csv"
    portfolio = PaperPortfolio(rm, str(log_path))

    opp = Opportunity(kind="cross_exchange", description="test", net_profit_pct=0.01, gross_profit_pct=0.01)
    trade = portfolio.execute(opp, trade_size_base=20.0)

    assert trade.pnl_base == 20.0 * 0.01
    assert rm.capital == 1000.0 + trade.pnl_base
    assert log_path.exists()

    with log_path.open() as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == 1
    assert rows[0]["kind"] == "cross_exchange"


def test_live_portfolio_records_actual_fill_pnl(tmp_path):
    rm = RiskManager(
        initial_capital=1000.0,
        max_trade_pct=0.02,
        min_profit_pct=0.003,
        max_daily_loss_pct=0.05,
    )
    log_path = tmp_path / "trades.csv"
    portfolio = LivePortfolio(rm, str(log_path))

    trade = portfolio.record_fill(
        kind="cross_exchange",
        description="real fill",
        quote_spent=100.0,
        quote_received=105.0,
    )

    assert trade.pnl_base == pytest.approx(5.0)
    assert trade.pnl_pct == pytest.approx(0.05)
    assert rm.capital == pytest.approx(1005.0)

    with log_path.open() as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == 1
    assert rows[0]["trade_size_base"] == "100.00000000"
