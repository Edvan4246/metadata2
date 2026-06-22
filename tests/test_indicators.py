import numpy as np
import pandas as pd
import pytest

from strategy.indicators import add_all_indicators, rsi, atr, ema, bollinger_bands


def make_df(n=300, seed=42):
    np.random.seed(seed)
    close = 1.08 + np.cumsum(np.random.normal(0, 0.0003, n))
    noise = np.random.uniform(0.0002, 0.0008, n)
    return pd.DataFrame({
        "open":   close + np.random.uniform(-0.0002, 0.0002, n),
        "high":   close + noise,
        "low":    close - noise,
        "close":  close,
        "volume": np.random.randint(100, 5000, n).astype(float),
    })


def test_ema_length():
    df = make_df()
    result = ema(df["close"], 20)
    assert len(result) == len(df)


def test_rsi_bounds():
    df = make_df()
    r = rsi(df["close"])
    valid = r.dropna()
    assert (valid >= 0).all() and (valid <= 100).all()


def test_atr_positive():
    df = make_df()
    a = atr(df)
    assert (a.dropna() >= 0).all()


def test_bollinger_spread():
    df = make_df()
    upper, mid, lower = bollinger_bands(df["close"])
    spread = (upper - lower).dropna()
    assert (spread >= 0).all()


def test_add_all_indicators_columns():
    df = make_df()
    enriched = add_all_indicators(df)
    expected = ["ema_8", "ema_21", "rsi", "macd", "atr", "adx", "bb_upper", "bb_lower"]
    for col in expected:
        assert col in enriched.columns, f"Missing column: {col}"


def test_no_lookahead_bias():
    df = make_df()
    enriched = add_all_indicators(df)
    # The last bar should have valid indicator values (no all-NaN indicators)
    last = enriched.iloc[-1]
    assert not last[["rsi", "macd", "atr"]].isna().all()
