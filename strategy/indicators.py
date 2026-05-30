"""
Technical indicator computation.
All functions accept a DataFrame with columns [open, high, low, close, volume]
and return a new DataFrame with original columns plus indicator columns.
No lookahead bias — all computations use only past data.
"""
import pandas as pd
import numpy as np


def ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False).mean()


def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    high_low = df["high"] - df["low"]
    high_close = (df["high"] - df["close"].shift(1)).abs()
    low_close = (df["low"] - df["close"].shift(1)).abs()
    true_range = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    return true_range.ewm(span=period, adjust=False).mean()


def rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    gain = delta.clip(lower=0).ewm(com=period - 1, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(com=period - 1, adjust=False).mean()
    rs = gain / loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def macd(series: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9):
    fast_ema = ema(series, fast)
    slow_ema = ema(series, slow)
    macd_line = fast_ema - slow_ema
    signal_line = ema(macd_line, signal)
    histogram = macd_line - signal_line
    return macd_line, signal_line, histogram


def bollinger_bands(series: pd.Series, period: int = 20, std_dev: float = 2.0):
    mid = series.rolling(period).mean()
    std = series.rolling(period).std()
    upper = mid + std_dev * std
    lower = mid - std_dev * std
    return upper, mid, lower


def stochastic(df: pd.DataFrame, k_period: int = 14, d_period: int = 3):
    low_min = df["low"].rolling(k_period).min()
    high_max = df["high"].rolling(k_period).max()
    k = 100 * (df["close"] - low_min) / (high_max - low_min).replace(0, np.nan)
    d = k.rolling(d_period).mean()
    return k, d


def adx(df: pd.DataFrame, period: int = 14) -> pd.Series:
    plus_dm = df["high"].diff()
    minus_dm = -df["low"].diff()
    plus_dm = plus_dm.where((plus_dm > minus_dm) & (plus_dm > 0), 0)
    minus_dm = minus_dm.where((minus_dm > plus_dm) & (minus_dm > 0), 0)

    atr_val = atr(df, period)
    plus_di = 100 * ema(plus_dm, period) / atr_val
    minus_di = 100 * ema(minus_dm, period) / atr_val
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    return ema(dx, period)


def add_all_indicators(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()

    # Trend
    df["ema_8"]   = ema(df["close"], 8)
    df["ema_21"]  = ema(df["close"], 21)
    df["ema_50"]  = ema(df["close"], 50)
    df["ema_200"] = ema(df["close"], 200)

    # Momentum
    df["rsi"]    = rsi(df["close"], 14)
    df["rsi_6"]  = rsi(df["close"], 6)

    macd_l, macd_s, macd_h = macd(df["close"])
    df["macd"]        = macd_l
    df["macd_signal"] = macd_s
    df["macd_hist"]   = macd_h

    df["stoch_k"], df["stoch_d"] = stochastic(df)

    # Volatility
    df["atr"]      = atr(df, 14)
    df["atr_pct"]  = df["atr"] / df["close"]

    bb_up, bb_mid, bb_low = bollinger_bands(df["close"])
    df["bb_upper"]  = bb_up
    df["bb_mid"]    = bb_mid
    df["bb_lower"]  = bb_low
    df["bb_width"]  = (bb_up - bb_low) / bb_mid
    df["bb_pct"]    = (df["close"] - bb_low) / (bb_up - bb_low).replace(0, np.nan)

    # Trend strength
    df["adx"] = adx(df, 14)

    # Price action features
    df["body"]       = (df["close"] - df["open"]).abs()
    df["upper_wick"] = df["high"] - df[["open", "close"]].max(axis=1)
    df["lower_wick"] = df[["open", "close"]].min(axis=1) - df["low"]
    df["candle_dir"] = np.where(df["close"] > df["open"], 1, -1)

    # Returns
    df["ret_1"]  = df["close"].pct_change(1)
    df["ret_3"]  = df["close"].pct_change(3)
    df["ret_10"] = df["close"].pct_change(10)

    return df


def add_lag_features(df: pd.DataFrame, lags: list = None) -> pd.DataFrame:
    """Add lagged close returns and RSI — gives tree models temporal memory."""
    df = df.copy()
    if lags is None:
        lags = [1, 2, 3, 5, 8, 13]
    for lag in lags:
        df[f"close_lag_{lag}"]  = df["close"].shift(lag)
        df[f"ret_lag_{lag}"]    = df["close"].pct_change(lag).shift(1)
        df[f"rsi_lag_{lag}"]    = df["rsi"].shift(lag) if "rsi" in df.columns else np.nan
    # Rolling statistics (short window)
    df["roll_mean_5"]  = df["close"].rolling(5).mean()
    df["roll_std_5"]   = df["close"].rolling(5).std()
    df["roll_mean_10"] = df["close"].rolling(10).mean()
    df["roll_std_10"]  = df["close"].rolling(10).std()
    # Normalise lags against current price so features are scale-invariant
    for lag in lags:
        df[f"close_lag_{lag}"] = (df[f"close_lag_{lag}"] - df["close"]) / df["close"]
    return df


def get_feature_columns(with_lags: bool = True) -> list:
    base = [
        "ema_8", "ema_21", "ema_50",
        "rsi", "rsi_6",
        "macd", "macd_signal", "macd_hist",
        "stoch_k", "stoch_d",
        "atr_pct", "bb_width", "bb_pct",
        "adx",
        "body", "upper_wick", "lower_wick", "candle_dir",
        "ret_1", "ret_3", "ret_10",
    ]
    if with_lags:
        lags = [1, 2, 3, 5, 8, 13]
        lag_cols = []
        for lag in lags:
            lag_cols += [f"close_lag_{lag}", f"ret_lag_{lag}", f"rsi_lag_{lag}"]
        lag_cols += ["roll_mean_5", "roll_std_5", "roll_mean_10", "roll_std_10"]
        return base + lag_cols
    return base
