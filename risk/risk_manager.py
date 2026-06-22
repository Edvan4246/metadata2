"""
Runtime risk guard — evaluated before every order open.

Rules enforced:
  1. Max open positions (global)
  2. Max one position per symbol
  3. Max daily drawdown (halt trading for the day)
  4. Max consecutive losses (circuit breaker)
  5. Per-symbol cooldown after a loss (reduces overtrading/revenge-trading)
"""
import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Dict, List

logger = logging.getLogger(__name__)


@dataclass
class RiskState:
    daily_start_balance: float = 0.0
    daily_date: date = field(default_factory=date.today)
    consecutive_losses: int = 0
    daily_trades: int = 0
    daily_pnl: float = 0.0
    halted: bool = False
    halt_reason: str = ""


class RiskManager:
    def __init__(
        self,
        max_open_positions: int = 4,
        max_daily_drawdown: float = 0.06,
        max_consecutive_losses: int = 5,
        max_daily_trades: int = 20,
        loss_cooldown_minutes: int = 45,
    ):
        self.max_open_positions = max_open_positions
        self.max_daily_drawdown = max_daily_drawdown
        self.max_consecutive_losses = max_consecutive_losses
        self.max_daily_trades = max_daily_trades
        self.loss_cooldown_minutes = loss_cooldown_minutes
        self.state = RiskState()
        self._symbol_cooldown_until: Dict[str, datetime] = {}

    def reset_daily(self, balance: float):
        today = date.today()
        if self.state.daily_date != today:
            logger.info("New trading day — resetting daily risk counters")
            self.state.daily_date = today
            self.state.daily_start_balance = balance
            self.state.daily_pnl = 0.0
            self.state.daily_trades = 0
            self.state.consecutive_losses = 0   # fresh start each day
            self.state.halted = False
            self.state.halt_reason = ""

    def can_open(self, symbol: str, open_positions: list, balance: float, equity: float) -> tuple[bool, str]:
        self.reset_daily(balance)

        if self.state.halted:
            return False, f"halted: {self.state.halt_reason}"

        if len(open_positions) >= self.max_open_positions:
            return False, f"max_positions_reached({len(open_positions)})"

        symbols_open = {p.symbol for p in open_positions}
        if symbol in symbols_open:
            return False, f"already_open({symbol})"

        cooldown_until = self._symbol_cooldown_until.get(symbol)
        if cooldown_until and datetime.utcnow() < cooldown_until:
            remaining = (cooldown_until - datetime.utcnow()).total_seconds() / 60
            return False, f"loss_cooldown({symbol},{remaining:.0f}min_left)"

        drawdown = (self.state.daily_start_balance - equity) / max(self.state.daily_start_balance, 1)
        if drawdown >= self.max_daily_drawdown:
            self._halt(f"daily_drawdown_{drawdown:.2%}")
            return False, self.state.halt_reason

        if self.state.consecutive_losses >= self.max_consecutive_losses:
            self._halt(f"consecutive_losses_{self.state.consecutive_losses}")
            return False, self.state.halt_reason

        if self.state.daily_trades >= self.max_daily_trades:
            return False, f"daily_trade_limit({self.state.daily_trades})"

        return True, "ok"

    def record_trade_closed(self, profit: float, symbol: str = ""):
        self.state.daily_pnl += profit
        self.state.daily_trades += 1
        if profit < 0:
            self.state.consecutive_losses += 1
            if symbol:
                self._symbol_cooldown_until[symbol] = datetime.utcnow() + timedelta(
                    minutes=self.loss_cooldown_minutes
                )
        else:
            self.state.consecutive_losses = 0

    def _halt(self, reason: str):
        if not self.state.halted:
            logger.warning("RISK HALT: %s", reason)
        self.state.halted = True
        self.state.halt_reason = reason

    def resume(self):
        self.state.halted = False
        self.state.halt_reason = ""
        logger.info("Risk manager resumed manually")

    def status(self) -> dict:
        return {
            "halted": self.state.halted,
            "halt_reason": self.state.halt_reason,
            "daily_pnl": round(self.state.daily_pnl, 2),
            "daily_trades": self.state.daily_trades,
            "consecutive_losses": self.state.consecutive_losses,
        }
