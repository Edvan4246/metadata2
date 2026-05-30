import numpy as np
import pandas as pd
import pytest

from backtesting.engine import BacktestEngine
from strategy.indicators import add_all_indicators


def make_df(n=600, seed=7):
    np.random.seed(seed)
    close = 1.08 + np.cumsum(np.random.normal(0.00002, 0.0003, n))
    noise = np.random.uniform(0.0003, 0.001, n)
    return pd.DataFrame({
        "open":   close + np.random.uniform(-0.0002, 0.0002, n),
        "high":   close + noise,
        "low":    close - noise,
        "close":  close,
        "volume": np.random.randint(100, 3000, n).astype(float),
    })


def test_backtest_no_trades_on_hold_signals():
    df = make_df()
    signals = pd.Series(0, index=df.index)
    engine = BacktestEngine()
    result = engine.run(df, signals, symbol="TEST")
    assert result.total_trades == 0


def test_backtest_produces_trades():
    df = make_df()
    # Alternate buy/sell signals
    signals = pd.Series([1 if i % 20 == 0 else (-1 if i % 20 == 10 else 0)
                         for i in range(len(df))], index=df.index)
    engine = BacktestEngine()
    result = engine.run(df, signals, symbol="TEST")
    assert result.total_trades > 0


def test_backtest_win_rate_in_bounds():
    df = make_df()
    signals = pd.Series([1 if i % 15 == 0 else 0 for i in range(len(df))], index=df.index)
    engine = BacktestEngine()
    result = engine.run(df, signals, symbol="TEST")
    assert 0.0 <= result.win_rate <= 1.0


def test_backtest_metrics_populated():
    df = make_df(n=800)
    signals = pd.Series([1 if i % 10 == 0 else 0 for i in range(len(df))], index=df.index)
    engine = BacktestEngine()
    result = engine.run(df, signals, symbol="EURUSD")

    assert result.total_trades >= 0
    assert isinstance(result.profit_factor, float)
    assert isinstance(result.max_drawdown, float)
    assert result.max_drawdown >= 0


def test_backtest_summary_string():
    df = make_df()
    signals = pd.Series([1 if i % 20 == 0 else 0 for i in range(len(df))], index=df.index)
    engine = BacktestEngine()
    result = engine.run(df, signals, symbol="EURUSD")
    summary = result.summary()
    assert "EURUSD" in summary
    assert "win_rate" in summary
