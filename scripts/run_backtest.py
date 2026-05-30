"""
Standalone backtest runner.
Uses simulated OHLCV from MT5Client (no live connection needed).
Trains ML model, generates walk-forward signals, runs backtest, prints report.

Usage: python scripts/run_backtest.py
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import logging
import pandas as pd
from core.mt5_client import MT5Client
from strategy.indicators import add_all_indicators
from strategy.ml_model import ForexMLModel
from backtesting.engine import BacktestEngine

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s — %(message)s")
logger = logging.getLogger("backtest")

SYMBOLS = ["EURUSD", "GBPUSD", "USDJPY"]
client = MT5Client(login=0, password="", server="")

for symbol in SYMBOLS:
    logger.info("Backtesting %s…", symbol)

    df = client.get_ohlcv(symbol, "M5", 1000)
    if df is None:
        logger.warning("No data for %s", symbol)
        continue

    model = ForexMLModel(symbol)
    report = model.train(df)
    logger.info("Training accuracy: %.3f", report.get("accuracy", 0))

    # Generate signals on the full dataset (walk-forward: model trained on first 80%)
    enriched = add_all_indicators(df)
    signals = pd.Series(0, index=df.index)
    for i in range(200, len(df)):
        sig, conf = model.predict(df.iloc[:i])
        signals.iloc[i] = sig if conf >= 0.52 else 0

    engine = BacktestEngine()
    result = engine.run(df, signals, symbol=symbol)
    print(result.summary())
