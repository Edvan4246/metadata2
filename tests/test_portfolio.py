from __future__ import annotations

import csv

from arbitrage_bot.models import Opportunity
from arbitrage_bot.portfolio import PaperPortfolio
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
