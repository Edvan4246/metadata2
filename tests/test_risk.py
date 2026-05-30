import pytest
from unittest.mock import MagicMock

from risk.risk_manager import RiskManager
from risk.position_sizing import calculate_lot_size


def make_position(symbol="EURUSD"):
    p = MagicMock()
    p.symbol = symbol
    return p


class TestRiskManager:
    def test_can_open_normal(self):
        rm = RiskManager(max_open_positions=4)
        rm.state.daily_start_balance = 10000
        ok, reason = rm.can_open("EURUSD", [], 10000, 10000)
        assert ok
        assert reason == "ok"

    def test_max_positions_blocks(self):
        rm = RiskManager(max_open_positions=2)
        rm.state.daily_start_balance = 10000
        positions = [make_position("EURUSD"), make_position("GBPUSD")]
        ok, reason = rm.can_open("USDJPY", positions, 10000, 10000)
        assert not ok
        assert "max_positions" in reason

    def test_duplicate_symbol_blocked(self):
        rm = RiskManager(max_open_positions=4)
        rm.state.daily_start_balance = 10000
        ok, reason = rm.can_open("EURUSD", [make_position("EURUSD")], 10000, 10000)
        assert not ok
        assert "already_open" in reason

    def test_daily_drawdown_halts(self):
        rm = RiskManager(max_daily_drawdown=0.06)
        rm.state.daily_start_balance = 10000
        # equity dropped 7% (below threshold)
        ok, reason = rm.can_open("EURUSD", [], 10000, 9200)
        assert not ok
        assert rm.state.halted

    def test_consecutive_losses_halt(self):
        rm = RiskManager(max_consecutive_losses=3)
        rm.state.daily_start_balance = 10000
        rm.state.consecutive_losses = 3
        ok, reason = rm.can_open("EURUSD", [], 10000, 10000)
        assert not ok

    def test_resume_clears_halt(self):
        rm = RiskManager()
        rm._halt("test_reason")
        assert rm.state.halted
        rm.resume()
        assert not rm.state.halted

    def test_record_trade_resets_on_win(self):
        rm = RiskManager()
        rm.state.consecutive_losses = 3
        rm.record_trade_closed(100.0)
        assert rm.state.consecutive_losses == 0

    def test_record_trade_increments_on_loss(self):
        rm = RiskManager()
        rm.state.consecutive_losses = 2
        rm.record_trade_closed(-50.0)
        assert rm.state.consecutive_losses == 3


class TestPositionSizing:
    def test_basic_sizing(self):
        lot = calculate_lot_size(
            equity=10000, risk_pct=0.02, entry=1.08500, sl=1.08000, symbol="EURUSD"
        )
        assert lot >= 0.01
        assert lot <= 10.0

    def test_tight_sl_gives_larger_lots(self):
        lot_tight = calculate_lot_size(10000, 0.02, 1.08500, 1.08400, "EURUSD")
        lot_wide  = calculate_lot_size(10000, 0.02, 1.08500, 1.07500, "EURUSD")
        assert lot_tight > lot_wide

    def test_zero_sl_returns_min(self):
        lot = calculate_lot_size(10000, 0.02, 1.085, 1.085, "EURUSD")
        assert lot == 0.01

    def test_jpy_pair_sizing(self):
        lot = calculate_lot_size(10000, 0.02, 149.500, 149.000, "USDJPY")
        assert lot >= 0.01

    def test_gold_sizing(self):
        # XAUUSD: entry=2350, SL=2335 → 15 points * $1/point/lot = $15 risk/lot
        lot = calculate_lot_size(10000, 0.02, 2350.0, 2335.0, "XAUUSD")
        assert lot >= 0.01
        assert lot <= 10.0

    def test_us100_sizing(self):
        # US100: entry=19200, SL=19150 → 50 points * $1/point/lot = $50 risk/lot
        lot = calculate_lot_size(10000, 0.02, 19200.0, 19150.0, "US100")
        assert lot >= 0.01
        assert lot <= 10.0

    def test_us30_sizing(self):
        lot = calculate_lot_size(10000, 0.02, 39500.0, 39400.0, "US30")
        assert lot >= 0.01
        assert lot <= 10.0
