from __future__ import annotations

import logging
from datetime import date

from arbitrage_bot.models import Opportunity

logger = logging.getLogger(__name__)


class RiskManager:
    """Enforces capital-protection rules for paper trading.

    Rules:
    - only acts on opportunities with net profit >= min_profit_pct
    - caps each trade at max_trade_pct of current capital
    - halts trading for the rest of the day once cumulative daily loss
      reaches max_daily_loss_pct of the capital at the start of the day
      (circuit breaker)
    """

    def __init__(
        self,
        initial_capital: float,
        max_trade_pct: float,
        min_profit_pct: float,
        max_daily_loss_pct: float,
    ):
        if initial_capital <= 0:
            raise ValueError("initial_capital must be positive")
        self.capital = initial_capital
        self.max_trade_pct = max_trade_pct
        self.min_profit_pct = min_profit_pct
        self.max_daily_loss_pct = max_daily_loss_pct

        self._current_day = date.today()
        self._daily_start_capital = initial_capital
        self.daily_pnl = 0.0
        self.trading_halted = False

    def _roll_day_if_needed(self) -> None:
        today = date.today()
        if today != self._current_day:
            self._current_day = today
            self._daily_start_capital = self.capital
            self.daily_pnl = 0.0
            self.trading_halted = False

    def evaluate(self, opportunity: Opportunity) -> float | None:
        """Returns the approved trade size (in base currency) or None if rejected."""
        self._roll_day_if_needed()

        if self.trading_halted:
            return None
        if opportunity.net_profit_pct < self.min_profit_pct:
            return None

        trade_size = self.capital * self.max_trade_pct
        return trade_size if trade_size > 0 else None

    def record_pnl(self, pnl_base: float) -> None:
        self._roll_day_if_needed()
        self.capital += pnl_base
        self.daily_pnl += pnl_base

        if self._daily_start_capital > 0:
            loss_pct = -self.daily_pnl / self._daily_start_capital
            if loss_pct >= self.max_daily_loss_pct:
                self.trading_halted = True
                logger.warning(
                    "Circuit breaker acionado: perda diaria de %.2f%% >= limite de %.2f%%. "
                    "Trading pausado pelo resto do dia.",
                    loss_pct * 100,
                    self.max_daily_loss_pct * 100,
                )
