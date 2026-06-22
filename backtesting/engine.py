"""
Backtesting engine with walk-forward validation.

Simulates the full signal → risk → execution pipeline on historical data,
producing a performance report with key metrics.
"""
import logging
from dataclasses import dataclass, field
from typing import List, Optional, Dict

import numpy as np
import pandas as pd

from strategy.indicators import add_all_indicators
from risk.position_sizing import INSTRUMENT_SPECS, _DEFAULT_SPEC, _FOREX_CONTRACT_SIZE

logger = logging.getLogger(__name__)


@dataclass
class Trade:
    symbol: str
    direction: int
    entry_bar: int
    entry_price: float
    sl: float
    tp: float
    volume: float
    exit_bar: Optional[int] = None
    exit_price: Optional[float] = None
    profit: float = 0.0
    exit_reason: str = ""


@dataclass
class BacktestResult:
    symbol: str
    total_trades: int
    win_rate: float
    profit_factor: float
    total_return: float
    max_drawdown: float
    sharpe_ratio: float
    avg_win: float
    avg_loss: float
    trades: List[Trade] = field(default_factory=list)

    def summary(self) -> str:
        return (
            f"[{self.symbol}] trades={self.total_trades} "
            f"win_rate={self.win_rate:.1%} "
            f"PF={self.profit_factor:.2f} "
            f"return={self.total_return:.2%} "
            f"maxDD={self.max_drawdown:.2%} "
            f"sharpe={self.sharpe_ratio:.2f}"
        )


class BacktestEngine:
    def __init__(
        self,
        initial_balance: float = 10_000,
        risk_per_trade: float = 0.02,
        atr_sl_mult: float = 1.0,
        atr_tp_mult: float = 3.0,
        commission_per_lot: float = 7.0,  # USD round-turn
        spread_points: int = 15,
    ):
        self.initial_balance = initial_balance
        self.risk_per_trade = risk_per_trade
        self.atr_sl_mult = atr_sl_mult
        self.atr_tp_mult = atr_tp_mult
        self.commission_per_lot = commission_per_lot
        self.spread_points = spread_points

    def run(self, df: pd.DataFrame, signals: pd.Series, symbol: str = "UNKNOWN") -> BacktestResult:
        """
        df      : OHLCV DataFrame (must include ATR column — call add_all_indicators first)
        signals : Series aligned with df index, values in {-1, 0, 1}
        """
        df = add_all_indicators(df.copy())
        if "atr" not in df.columns:
            raise ValueError("ATR not in DataFrame — call add_all_indicators first")

        balance = self.initial_balance
        equity_curve = [balance]
        trades: List[Trade] = []
        open_trade: Optional[Trade] = None

        for i in range(1, len(df)):
            row = df.iloc[i]
            prev = df.iloc[i - 1]
            signal = signals.iloc[i - 1] if i - 1 < len(signals) else 0

            # Check exit on open trade
            if open_trade is not None:
                pnl, reason = self._check_exit(open_trade, row)
                if pnl is not None:
                    open_trade.exit_bar = i
                    open_trade.exit_price = row["open"]
                    open_trade.profit = pnl
                    open_trade.exit_reason = reason
                    balance += pnl
                    trades.append(open_trade)
                    open_trade = None

            # Open new trade
            if open_trade is None and signal != 0:
                atr = prev["atr"]
                entry = row["open"]
                if signal == 1:
                    sl = entry - self.atr_sl_mult * atr
                    tp = entry + self.atr_tp_mult * atr
                else:
                    sl = entry + self.atr_sl_mult * atr
                    tp = entry - self.atr_tp_mult * atr

                open_trade = Trade(
                    symbol=symbol,
                    direction=signal,
                    entry_bar=i,
                    entry_price=entry,
                    sl=sl,
                    tp=tp,
                    volume=0.01,
                )

            equity_curve.append(balance)

        # Close any still-open trade at last bar
        if open_trade is not None:
            last = df.iloc[-1]
            open_trade.exit_bar = len(df) - 1
            open_trade.exit_price = last["close"]
            open_trade.profit = self._calc_pnl(open_trade, last["close"])
            open_trade.exit_reason = "end_of_data"
            balance += open_trade.profit
            trades.append(open_trade)

        return self._compute_metrics(trades, np.array(equity_curve), symbol)

    def _check_exit(self, trade: Trade, row: pd.Series):
        if trade.direction == 1:
            if row["low"] <= trade.sl:
                return self._calc_pnl(trade, trade.sl), "sl"
            if row["high"] >= trade.tp:
                return self._calc_pnl(trade, trade.tp), "tp"
        else:
            if row["high"] >= trade.sl:
                return self._calc_pnl(trade, trade.sl), "sl"
            if row["low"] <= trade.tp:
                return self._calc_pnl(trade, trade.tp), "tp"
        return None, ""

    def _calc_pnl(self, trade: Trade, exit_price: float) -> float:
        sym = trade.symbol.upper().replace(".", "").replace("-", "")
        point_size, pip_val = INSTRUMENT_SPECS.get(sym, _DEFAULT_SPEC)

        # For JPY pairs pip_val is None → compute dynamically from entry price
        if pip_val is None:
            pip_val = (point_size / trade.entry_price) * _FOREX_CONTRACT_SIZE

        points = (exit_price - trade.entry_price) / point_size * trade.direction
        gross = points * pip_val * trade.volume
        commission = self.commission_per_lot * trade.volume
        return gross - commission

    def _compute_metrics(self, trades: List[Trade], equity: np.ndarray, symbol: str) -> BacktestResult:
        if not trades:
            return BacktestResult(
                symbol=symbol, total_trades=0, win_rate=0, profit_factor=0,
                total_return=0, max_drawdown=0, sharpe_ratio=0,
                avg_win=0, avg_loss=0, trades=[],
            )

        profits = [t.profit for t in trades]
        wins = [p for p in profits if p > 0]
        losses = [p for p in profits if p <= 0]

        win_rate = len(wins) / len(trades)
        profit_factor = sum(wins) / max(abs(sum(losses)), 1e-9) if losses else float("inf")
        total_return = (equity[-1] - equity[0]) / equity[0]

        # Max drawdown
        peak = np.maximum.accumulate(equity)
        drawdowns = (equity - peak) / np.maximum(peak, 1)
        max_drawdown = float(abs(drawdowns.min()))

        # Sharpe (daily returns)
        ret = np.diff(equity) / np.maximum(equity[:-1], 1)
        sharpe = float(np.mean(ret) / (np.std(ret) + 1e-9) * np.sqrt(252)) if len(ret) > 1 else 0

        return BacktestResult(
            symbol=symbol,
            total_trades=len(trades),
            win_rate=win_rate,
            profit_factor=profit_factor,
            total_return=total_return,
            max_drawdown=max_drawdown,
            sharpe_ratio=sharpe,
            avg_win=float(np.mean(wins)) if wins else 0,
            avg_loss=float(np.mean(losses)) if losses else 0,
            trades=trades,
        )
