from __future__ import annotations

from arbitrage_bot.models import Opportunity
from arbitrage_bot.risk import RiskManager


def make_risk_manager(**overrides) -> RiskManager:
    params = dict(
        initial_capital=1000.0,
        max_trade_pct=0.02,
        min_profit_pct=0.003,
        max_daily_loss_pct=0.05,
    )
    params.update(overrides)
    return RiskManager(**params)


def make_opportunity(net_profit_pct: float) -> Opportunity:
    return Opportunity(
        kind="cross_exchange",
        description="test",
        net_profit_pct=net_profit_pct,
        gross_profit_pct=net_profit_pct,
    )


def test_rejects_opportunity_below_min_profit():
    rm = make_risk_manager()
    assert rm.evaluate(make_opportunity(0.001)) is None


def test_approves_trade_capped_at_max_trade_pct():
    rm = make_risk_manager()
    trade_size = rm.evaluate(make_opportunity(0.01))
    assert trade_size == rm.capital * rm.max_trade_pct


def test_candidate_trade_size_below_cap_is_used_as_is():
    rm = make_risk_manager()
    small_candidate = rm.capital * rm.max_trade_pct / 2
    trade_size = rm.evaluate(make_opportunity(0.01), candidate_trade_size=small_candidate)
    assert trade_size == small_candidate


def test_candidate_trade_size_above_cap_is_still_capped():
    rm = make_risk_manager()
    huge_candidate = rm.capital * rm.max_trade_pct * 10
    trade_size = rm.evaluate(make_opportunity(0.01), candidate_trade_size=huge_candidate)
    assert trade_size == rm.capital * rm.max_trade_pct


def test_circuit_breaker_halts_after_daily_loss_limit():
    rm = make_risk_manager(initial_capital=1000.0, max_daily_loss_pct=0.05)
    rm.record_pnl(-60.0)  # 6% loss > 5% limit
    assert rm.trading_halted is True
    assert rm.evaluate(make_opportunity(0.5)) is None


def test_initial_capital_must_be_positive():
    try:
        make_risk_manager(initial_capital=0)
    except ValueError:
        pass
    else:
        raise AssertionError("expected ValueError for non-positive initial_capital")
