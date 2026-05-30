"""
ML ensemble model for forex signal generation.

Architecture:
  - Features: technical indicators + price action features
  - Labels: forward return > threshold → BUY(1), < -threshold → SELL(-1), else HOLD(0)
  - Models: RandomForest + GradientBoosting, soft-voted ensemble
  - Training: walk-forward to prevent lookahead bias
  - Persistence: joblib serialization per symbol
"""
import logging
import os
from typing import Optional, Tuple

import numpy as np
import pandas as pd
import joblib
from sklearn.ensemble import RandomForestClassifier, GradientBoostingClassifier
from sklearn.preprocessing import StandardScaler
from sklearn.pipeline import Pipeline
from sklearn.metrics import classification_report

from strategy.indicators import add_all_indicators, get_feature_columns

logger = logging.getLogger(__name__)

MODELS_DIR = "models"
os.makedirs(MODELS_DIR, exist_ok=True)

FORWARD_BARS = 3      # predict return N bars ahead
SIGNAL_THRESHOLD = 0.0003  # 3 pips minimum move to label as BUY/SELL


def _build_labels(df: pd.DataFrame) -> pd.Series:
    future_ret = df["close"].shift(-FORWARD_BARS) / df["close"] - 1
    labels = pd.Series(0, index=df.index, dtype=int)
    labels[future_ret > SIGNAL_THRESHOLD]  = 1   # BUY
    labels[future_ret < -SIGNAL_THRESHOLD] = -1  # SELL
    return labels


def _make_pipeline(n_estimators: int = 200) -> Pipeline:
    rf = RandomForestClassifier(
        n_estimators=n_estimators,
        max_depth=6,
        min_samples_leaf=20,
        class_weight="balanced",
        random_state=42,
        n_jobs=-1,
    )
    gb = GradientBoostingClassifier(
        n_estimators=n_estimators // 2,
        max_depth=4,
        learning_rate=0.05,
        subsample=0.8,
        random_state=42,
    )
    # We'll store both models; prediction is a soft vote
    return rf, gb


class ForexMLModel:
    def __init__(self, symbol: str):
        self.symbol = symbol
        self.rf: Optional[Pipeline] = None
        self.gb: Optional[Pipeline] = None
        self.scaler = StandardScaler()
        self.feature_cols = get_feature_columns()
        self._trained = False

    # ------------------------------------------------------------------
    # Training
    # ------------------------------------------------------------------

    def train(self, df: pd.DataFrame) -> dict:
        enriched = add_all_indicators(df)
        labels = _build_labels(enriched)

        # Drop NaN rows (from indicator warm-up and forward label shift)
        valid = enriched[self.feature_cols].join(labels.rename("label")).dropna()
        valid = valid[:-FORWARD_BARS]  # last N bars have no valid forward return

        X = valid[self.feature_cols].values
        y = valid["label"].values

        if len(X) < 200:
            logger.warning("%s: insufficient data (%d rows) for training", self.symbol, len(X))
            return {}

        # Walk-forward split: last 20% = test
        split = int(len(X) * 0.8)
        X_train, X_test = X[:split], X[split:]
        y_train, y_test = y[:split], y[split:]

        X_train_scaled = self.scaler.fit_transform(X_train)
        X_test_scaled  = self.scaler.transform(X_test)

        self.rf, self.gb = _make_pipeline()
        self.rf.fit(X_train_scaled, y_train)
        self.gb.fit(X_train_scaled, y_train)

        rf_preds = self.rf.predict(X_test_scaled)
        report = classification_report(y_test, rf_preds, output_dict=True, zero_division=0)
        logger.info("%s model trained | test accuracy=%.3f | rows=%d",
                    self.symbol, report.get("accuracy", 0), len(X))

        self._trained = True
        self.save()
        return report

    # ------------------------------------------------------------------
    # Prediction
    # ------------------------------------------------------------------

    def predict(self, df: pd.DataFrame) -> Tuple[int, float]:
        """Return (signal, confidence) where signal ∈ {-1, 0, 1}."""
        if not self._trained:
            return 0, 0.0

        enriched = add_all_indicators(df)
        row = enriched[self.feature_cols].iloc[[-1]].dropna()
        if row.empty:
            return 0, 0.0

        X = self.scaler.transform(row.values)

        rf_proba = self.rf.predict_proba(X)[0]
        gb_proba = self.gb.predict_proba(X)[0]
        classes = self.rf.classes_

        avg_proba = (rf_proba + gb_proba) / 2
        best_idx = int(np.argmax(avg_proba))
        signal = int(classes[best_idx])
        confidence = float(avg_proba[best_idx])

        # Only act on high-confidence non-neutral signals
        if signal == 0 or confidence < 0.50:
            return 0, confidence

        return signal, confidence

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def save(self):
        path = os.path.join(MODELS_DIR, f"{self.symbol}.pkl")
        joblib.dump({"rf": self.rf, "gb": self.gb, "scaler": self.scaler}, path)
        logger.debug("Model saved: %s", path)

    def load(self) -> bool:
        path = os.path.join(MODELS_DIR, f"{self.symbol}.pkl")
        if not os.path.exists(path):
            return False
        data = joblib.load(path)
        self.rf      = data["rf"]
        self.gb      = data["gb"]
        self.scaler  = data["scaler"]
        self._trained = True
        logger.info("Model loaded: %s", path)
        return True

    @property
    def is_trained(self) -> bool:
        return self._trained
