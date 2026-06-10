"""
Confidence-threshold sweep — compares ML confidence thresholds per symbol
to find a value that improves win rate / profit factor vs the current 0.48.

Connects to MT5 using credentials from .env for real historical data.
Usage: python scripts/run_threshold_sweep.py
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import logging
import numpy as np
import pandas as pd

from core.mt5_client import MT5Client
from strategy.indicators import add_all_indicators, add_lag_features, get_feature_columns
from strategy.ml_model import ForexMLModel
from backtesting.engine import BacktestEngine
from config.settings import settings

logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s — %(message)s")
logger = logging.getLogger("sweep")

SYMBOLS = ["EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "XAUUSD", "US100", "US30", "BTCUSD", "ETHUSD"]
THRESHOLDS = [0.48, 0.55, 0.60, 0.65]

COOLDOWN_BARS: dict = {
    "XAUUSD": 12,
    "US100":  10,
    "US30":   10,
    "BTCUSD": 12,
    "ETHUSD": 12,
    "default": 6,
}

BARS = 10_000  # ~33 dias uteis de M5

client = MT5Client(
    login=settings.mt5_login,
    password=settings.mt5_password,
    server=settings.mt5_server,
    magic=settings.magic_number,
)

if not client.connect():
    logger.error("Nao foi possivel conectar ao MT5. Verifique o .env e se o MT5 esta aberto.")
    sys.exit(1)

logger.info("MT5 conectado com sucesso!")

print("\n" + "=" * 90)
print(f"{'SYMBOL':<10} {'THRESH':>7} {'TRADES':>7} {'WIN%':>8} {'PF':>6} {'RETURN':>9} {'MAX DD':>8} {'SHARPE':>8}")
print("=" * 90)

for symbol in SYMBOLS:
    df = client.get_ohlcv(symbol, "M5", BARS)
    if df is None:
        logger.warning("No data for %s", symbol)
        continue

    split = int(len(df) * 0.70)
    model = ForexMLModel(symbol)
    model.train(df.iloc[:split])

    test_df = df.iloc[split:].copy()
    enriched = add_all_indicators(test_df)
    enriched = add_lag_features(enriched)
    feat_cols = [c for c in get_feature_columns(with_lags=True) if c in enriched.columns]

    valid_rows = enriched[feat_cols].dropna()
    if valid_rows.empty or not model.is_trained:
        logger.warning("Cannot generate signals for %s", symbol)
        continue

    X = model.scaler.transform(valid_rows.values)

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
    best_idx = np.argmax(avg_proba, axis=1)
    raw_signals = np.array([y_map_inv[i] for i in best_idx])
    confidence = avg_proba[np.arange(len(avg_proba)), best_idx]

    cooldown = COOLDOWN_BARS.get(symbol, COOLDOWN_BARS["default"])

    for thresh in THRESHOLDS:
        signals_raw = np.where(
            (raw_signals != 0) & (confidence >= thresh),
            raw_signals,
            0,
        )

        # Apply cooldown
        signals_cd = signals_raw.copy()
        last_signal_bar = -cooldown
        for i, sig in enumerate(signals_cd):
            if sig != 0:
                if i - last_signal_bar < cooldown:
                    signals_cd[i] = 0
                else:
                    last_signal_bar = i

        signals = pd.Series(0, index=test_df.index, dtype=int)
        signals.loc[valid_rows.index] = signals_cd

        engine = BacktestEngine()
        result = engine.run(test_df, signals, symbol=symbol)

        print(
            f"{symbol:<10} {thresh:>7.2f} {result.total_trades:>7} "
            f"{result.win_rate:>7.1%} "
            f"{result.profit_factor:>6.2f} "
            f"{result.total_return:>8.2%} "
            f"{result.max_drawdown:>7.2%} "
            f"{result.sharpe_ratio:>8.2f}"
        )
    print("-" * 90)

print("=" * 90)
client.disconnect()
