"""
Standalone backtest runner — vectorized signal generation.
Uses simulated OHLCV from MT5Client (no live connection needed).

Usage: python scripts/run_backtest.py
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import logging
import pandas as pd
import numpy as np

from core.mt5_client import MT5Client
from strategy.indicators import add_all_indicators, add_lag_features, get_feature_columns
from strategy.ml_model import ForexMLModel
from backtesting.engine import BacktestEngine

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s — %(message)s")
logger = logging.getLogger("backtest")

SYMBOLS = ["EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCAD", "XAUUSD", "US100", "US30"]
CONFIDENCE_THRESHOLD = 0.50

client = MT5Client(login=0, password="", server="")

print("\n" + "="*72)
print(f"{'SYMBOL':<10} {'TRADES':>7} {'WIN%':>8} {'PF':>6} {'RETURN':>9} {'MAX DD':>8} {'SHARPE':>8}")
print("="*72)

for symbol in SYMBOLS:
    df = client.get_ohlcv(symbol, "M5", 1200)
    if df is None:
        logger.warning("No data for %s", symbol)
        continue

    # Train on first 70%
    split = int(len(df) * 0.70)
    model = ForexMLModel(symbol)
    model.train(df.iloc[:split])

    # Vectorized signal generation on test set (last 30%)
    test_df = df.iloc[split:].copy()
    enriched = add_all_indicators(test_df)
    enriched = add_lag_features(enriched)
    feat_cols = [c for c in get_feature_columns(with_lags=True) if c in enriched.columns]

    valid_rows = enriched[feat_cols].dropna()
    if valid_rows.empty or not model.is_trained:
        logger.warning("Cannot generate signals for %s", symbol)
        continue

    X = model.scaler.transform(valid_rows.values)

    # XGBoost + LightGBM + RF ensemble (labels mapped: 0→-1, 1→0, 2→+1)
    y_map_inv = {0: -1, 1: 0, 2: 1}
    xgb_p = model.xgb_model.predict_proba(X)
    lgb_p = model.lgb_model.predict_proba(X)

    rf_raw = model.rf_model.predict_proba(X)
    rf_classes = model.rf_model.classes_
    rf_p = np.zeros((len(X), 3))
    for i, cls in enumerate(rf_classes):
        col = {-1: 0, 0: 1, 1: 2}.get(int(cls), 1)
        rf_p[:, col] = rf_raw[:, i]

    avg_proba = (xgb_p + lgb_p + rf_p) / 3
    best_idx   = np.argmax(avg_proba, axis=1)
    raw_signals = np.array([y_map_inv[i] for i in best_idx])
    confidence  = avg_proba[np.arange(len(avg_proba)), best_idx]

    signals_filtered = np.where(
        (raw_signals != 0) & (confidence >= CONFIDENCE_THRESHOLD),
        raw_signals,
        0,
    )

    signals = pd.Series(0, index=test_df.index, dtype=int)
    signals.loc[valid_rows.index] = signals_filtered

    engine = BacktestEngine()
    result = engine.run(test_df, signals, symbol=symbol)

    print(
        f"{symbol:<10} {result.total_trades:>7} "
        f"{result.win_rate:>7.1%} "
        f"{result.profit_factor:>6.2f} "
        f"{result.total_return:>8.2%} "
        f"{result.max_drawdown:>7.2%} "
        f"{result.sharpe_ratio:>8.2f}"
    )

print("="*72)
print(f"\nNote: results use simulated price data (no live MT5 connection).")
print("Connect MT5 and use real historical data for meaningful results.\n")
