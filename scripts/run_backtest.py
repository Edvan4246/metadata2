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
from strategy.indicators import add_all_indicators, get_feature_columns
from strategy.ml_model import ForexMLModel
from backtesting.engine import BacktestEngine

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s — %(message)s")
logger = logging.getLogger("backtest")

SYMBOLS = ["EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCAD"]
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
    feat_cols = get_feature_columns()

    valid_rows = enriched[feat_cols].dropna()
    if valid_rows.empty or not model.is_trained:
        logger.warning("Cannot generate signals for %s", symbol)
        continue

    X = model.scaler.transform(valid_rows.values)
    rf_proba = model.rf.predict_proba(X)
    gb_proba = model.gb.predict_proba(X)
    avg_proba = (rf_proba + gb_proba) / 2
    classes = model.rf.classes_

    best_idx = np.argmax(avg_proba, axis=1)
    raw_signals = classes[best_idx]
    confidence = avg_proba[np.arange(len(avg_proba)), best_idx]

    # Apply confidence threshold and neutral filter
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
