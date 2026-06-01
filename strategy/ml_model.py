"""
ML ensemble model — XGBoost + LightGBM + RandomForest.

Why XGBoost/LightGBM instead of LSTM:
  Tree ensembles consistently outperform LSTMs on tabular financial data
  (M5/H1 OHLCV), require far less data, train in seconds, and don't
  overfit as easily. Temporal awareness is achieved via lag features.

Architecture:
  - Features: 40+ technical indicators + 24 lag/rolling features
  - Labels: forward return > threshold → BUY(1), < -threshold → SELL(-1), else HOLD(0)
  - Models: XGBoost + LightGBM + RandomForest — soft-vote ensemble
  - Training: walk-forward 80/20 split
  - Persistence: joblib per symbol
"""
import logging
import os
from typing import Optional, Tuple

import numpy as np
import pandas as pd
import joblib
from sklearn.ensemble import RandomForestClassifier
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import classification_report

import xgboost as xgb
import lightgbm as lgb

from strategy.indicators import add_all_indicators, add_lag_features, get_feature_columns

logger = logging.getLogger(__name__)

MODELS_DIR = "models"
os.makedirs(MODELS_DIR, exist_ok=True)

FORWARD_BARS   = 6      # look 6 bars ahead (30 min on M5)
ATR_LABEL_MULT = 0.6   # label BUY/SELL if future move ≥ 0.6×ATR


def _build_labels(df: pd.DataFrame) -> pd.Series:
    """
    ATR-adaptive labeling: threshold scales with each bar's volatility.
    This aligns labels with the actual SL/TP distances used in trading
    and works correctly across all instruments (forex, gold, indices).
    """
    from strategy.indicators import atr as calc_atr
    atr_series = calc_atr(df, 14)
    threshold = atr_series * ATR_LABEL_MULT   # dynamic per bar

    future_price  = df["close"].shift(-FORWARD_BARS)
    future_move   = future_price - df["close"]

    labels = pd.Series(0, index=df.index, dtype=int)
    labels[future_move >  threshold] =  1
    labels[future_move < -threshold] = -1
    return labels


class ForexMLModel:
    def __init__(self, symbol: str):
        self.symbol = symbol
        self.xgb_model  = None
        self.lgb_model  = None
        self.rf_model   = None
        self.scaler     = StandardScaler()
        self.feature_cols = get_feature_columns(with_lags=True)
        self._trained   = False
        self._classes   = np.array([-1, 0, 1])

    # ------------------------------------------------------------------
    # Training
    # ------------------------------------------------------------------

    def train(self, df: pd.DataFrame) -> dict:
        enriched = add_all_indicators(df)
        enriched = add_lag_features(enriched)
        labels   = _build_labels(enriched)

        valid_cols = [c for c in self.feature_cols if c in enriched.columns]
        data = enriched[valid_cols].join(labels.rename("label")).dropna()
        data = data[:-FORWARD_BARS]

        X = data[valid_cols].values
        y = data["label"].values

        if len(X) < 200:
            logger.warning("%s: insufficient data (%d rows) for training", self.symbol, len(X))
            return {}

        split = int(len(X) * 0.8)
        X_train, X_test = X[:split], X[split:]
        y_train, y_test = y[:split], y[split:]

        X_tr = self.scaler.fit_transform(X_train)
        X_te = self.scaler.transform(X_test)

        # XGBoost
        self.xgb_model = xgb.XGBClassifier(
            n_estimators=300,
            max_depth=5,
            learning_rate=0.05,
            subsample=0.8,
            colsample_bytree=0.8,
            use_label_encoder=False,
            eval_metric="mlogloss",
            random_state=42,
            verbosity=0,
        )
        # XGBoost needs labels 0,1,2 → remap
        y_map = {-1: 0, 0: 1, 1: 2}
        y_tr_xgb = np.array([y_map[v] for v in y_train])
        y_te_xgb = np.array([y_map[v] for v in y_test])
        self.xgb_model.fit(X_tr, y_tr_xgb)

        # LightGBM
        self.lgb_model = lgb.LGBMClassifier(
            n_estimators=300,
            max_depth=5,
            learning_rate=0.05,
            subsample=0.8,
            colsample_bytree=0.8,
            num_leaves=31,
            random_state=42,
            verbose=-1,
        )
        y_tr_lgb = np.array([y_map[v] for v in y_train])
        self.lgb_model.fit(X_tr, y_tr_lgb)

        # RandomForest (diversity in ensemble)
        self.rf_model = RandomForestClassifier(
            n_estimators=200,
            max_depth=6,
            min_samples_leaf=20,
            class_weight="balanced",
            random_state=42,
            n_jobs=-1,
        )
        self.rf_model.fit(X_tr, y_train)   # RF keeps original labels

        xgb_acc = (self.xgb_model.predict(X_te) == y_te_xgb).mean()
        logger.info(
            "%s trained | XGB acc=%.3f | rows=%d | features=%d",
            self.symbol, xgb_acc, len(X), len(valid_cols),
        )

        self._trained     = True
        self.feature_cols = valid_cols
        self.save()
        return {"accuracy": float(xgb_acc)}

    # ------------------------------------------------------------------
    # Prediction
    # ------------------------------------------------------------------

    def predict(self, df: pd.DataFrame) -> Tuple[int, float]:
        """Return (signal, confidence) where signal ∈ {-1, 0, 1}."""
        if not self._trained:
            return 0, 0.0

        enriched = add_all_indicators(df)
        enriched = add_lag_features(enriched)

        valid_cols = [c for c in self.feature_cols if c in enriched.columns]
        row = enriched[valid_cols].iloc[[-1]].dropna()
        if row.empty or row.shape[1] != len(valid_cols):
            return 0, 0.0

        X = self.scaler.transform(row.values)
        y_map_inv = {0: -1, 1: 0, 2: 1}

        import warnings
        with warnings.catch_warnings():
            warnings.filterwarnings("ignore", category=UserWarning)
            xgb_p = self.xgb_model.predict_proba(X)[0]
            lgb_p = self.lgb_model.predict_proba(X)[0]

        # RandomForest probabilities (classes: -1, 0, 1 → needs alignment)
        rf_raw = self.rf_model.predict_proba(X)[0]
        rf_classes = self.rf_model.classes_
        rf_p = np.zeros(3)
        for i, cls in enumerate(rf_classes):
            idx = {-1: 0, 0: 1, 1: 2}.get(int(cls), 1)
            rf_p[idx] = rf_raw[i]

        # Soft vote (equal weights)
        avg_p = (xgb_p + lgb_p + rf_p) / 3
        best_idx  = int(np.argmax(avg_p))
        signal    = y_map_inv[best_idx]
        confidence = float(avg_p[best_idx])

        if signal == 0 or confidence < 0.48:
            return 0, confidence

        return signal, confidence

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def save(self):
        path = os.path.join(MODELS_DIR, f"{self.symbol}.pkl")
        joblib.dump({
            "xgb": self.xgb_model,
            "lgb": self.lgb_model,
            "rf":  self.rf_model,
            "scaler": self.scaler,
            "feature_cols": self.feature_cols,
        }, path)

    def load(self) -> bool:
        path = os.path.join(MODELS_DIR, f"{self.symbol}.pkl")
        if not os.path.exists(path):
            return False
        data = joblib.load(path)
        self.xgb_model    = data["xgb"]
        self.lgb_model    = data["lgb"]
        self.rf_model     = data["rf"]
        self.scaler       = data["scaler"]
        self.feature_cols = data.get("feature_cols", self.feature_cols)
        self._trained     = True
        logger.info("Model loaded: %s", path)
        return True

    @property
    def is_trained(self) -> bool:
        return self._trained
