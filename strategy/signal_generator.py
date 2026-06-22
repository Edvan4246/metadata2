"""
Signal generator — routes to trend or mean-reversion strategy based on regime.

Signal flow:
  [Session filter]  → off-hours? → skip
  [H4 ADX]
      ≥ 18 → Trend strategy: ML M5 + H1 EMA filter + H4 ADX filter
      < 18 → Mean-reversion: BB touch + RSI/Stoch extremes
  [Spread filter]   → too wide? → skip
"""
import logging
from typing import Optional, Dict

import pandas as pd

from strategy.types import SignalResult
from strategy.indicators import add_all_indicators
from strategy.ml_model import ForexMLModel
from strategy.mean_reversion import generate_mean_reversion_signal
from core.mt5_client import MT5Client
from core.session_filter import is_tradeable, session_name

logger = logging.getLogger(__name__)


# Per-symbol max spread thresholds (in broker points).
# Indices and metals have wider spreads than standard forex pairs.
MAX_SPREAD_BY_SYMBOL: dict[str, int] = {
    "XAUUSD": 80,    # Gold — typical spread $0.30–0.80
    "XAGUSD": 120,
    "US100":  5,     # Nasdaq — typically 1–3 points
    "US30":   8,     # Dow Jones — typically 2–5 points
    "US500":  5,
    "GER40":  5,
    "UK100":  8,
    "BTCUSD": 200,
    "ETHUSD": 50,
}
DEFAULT_MAX_SPREAD = 30   # forex pairs

# Price rounding per instrument (decimal places for SL/TP)
PRICE_DECIMALS: dict[str, int] = {
    "XAUUSD": 2,
    "US100":  1,
    "US30":   1,
    "US500":  1,
    "GER40":  1,
    "UK100":  1,
    "BTCUSD": 2,
}
DEFAULT_PRICE_DECIMALS = 5

# Minimum ATR floor per instrument (in price units) used for SL/TP sizing.
# Prevents stops from collapsing to ~1 pip during very low-volatility
# periods, which causes rapid repeated stop-outs from normal noise/spread.
MIN_ATR_BY_SYMBOL: dict[str, float] = {
    "XAUUSD": 0.50,
    "XAGUSD": 0.05,
    "US100":  5.0,
    "US30":   10.0,
    "US500":  2.0,
    "GER40":  5.0,
    "UK100":  5.0,
    "BTCUSD": 50.0,
    "ETHUSD": 5.0,
    "USDJPY": 0.05,
    "EURJPY": 0.05,
    "GBPJPY": 0.05,
    "AUDJPY": 0.05,
}
DEFAULT_MIN_ATR = 0.0005   # 5 pips for standard 5-decimal forex pairs


class SignalGenerator:
    def __init__(
        self,
        client: MT5Client,
        models: Dict[str, ForexMLModel],
        max_spread: int = DEFAULT_MAX_SPREAD,
        atr_sl_mult: float = 1.0,
        atr_tp_mult: float = 3.0,
    ):
        self.client = client
        self.models = models
        self.max_spread = max_spread
        self.atr_sl_mult = atr_sl_mult
        self.atr_tp_mult = atr_tp_mult

    def _max_spread(self, symbol: str) -> int:
        return MAX_SPREAD_BY_SYMBOL.get(symbol.upper(), self.max_spread)

    def _min_atr(self, symbol: str) -> float:
        return MIN_ATR_BY_SYMBOL.get(symbol.upper(), DEFAULT_MIN_ATR)

    def _price_decimals(self, symbol: str) -> int:
        return PRICE_DECIMALS.get(symbol.upper(), DEFAULT_PRICE_DECIMALS)

    def generate(self, symbol: str, ohlcv: Dict[str, pd.DataFrame]) -> SignalResult:
        tick = self.client.get_tick(symbol)
        entry = tick.ask if tick else 0.0
        spread = tick.spread if tick else 999

        null_signal = SignalResult(
            symbol=symbol, direction=0, confidence=0,
            ml_signal=0, ml_confidence=0, h1_trend=0, h4_adx=0,
            spread=spread, atr=0, entry_price=entry,
            sl=0, tp=0, reason="no_data",
        )

        if "M5" not in ohlcv or "H1" not in ohlcv or "H4" not in ohlcv:
            return null_signal

        # Session filter — only trade in high-liquidity windows
        if not is_tradeable(symbol):
            null_signal.reason = f"off_hours({session_name()})"
            return null_signal

        # Per-symbol spread filter
        symbol_max_spread = self._max_spread(symbol)
        if spread > symbol_max_spread:
            null_signal.reason = f"spread_too_high({spread}>{symbol_max_spread})"
            return null_signal

        # --- Regime detection via H4 ADX ---
        h4 = add_all_indicators(ohlcv["H4"])
        h4_adx = float(h4["adx"].iloc[-1]) if not pd.isna(h4["adx"].iloc[-1]) else 0
        null_signal.h4_adx = h4_adx  # propagate real ADX to all early-return paths

        # RANGING regime → mean-reversion strategy
        if h4_adx < 18:
            mr = generate_mean_reversion_signal(
                symbol=symbol,
                ohlcv=ohlcv,
                entry_price=entry,
                spread=spread,
                max_spread=symbol_max_spread,
                h4_adx=h4_adx,
                price_decimals=self._price_decimals(symbol),
            )
            if mr is not None:
                return mr
            null_signal.reason = f"mr_no_signal(adx={h4_adx:.1f})"
            return null_signal

        # TRENDING regime → ML + multi-TF trend strategy
        model = self.models.get(symbol)
        ml_signal, ml_conf = (0, 0.0)
        if model and model.is_trained:
            ml_signal, ml_conf = model.predict(ohlcv["M5"])

        if ml_signal == 0:
            null_signal.reason = "ml_hold"
            null_signal.ml_signal = ml_signal
            null_signal.ml_confidence = ml_conf
            return null_signal

        # H4 EMA trend guard — volatile assets must trade WITH the H4 trend
        # Prevents shorting gold/indices in a strong uptrend (and vice-versa)
        _TREND_GUARD = {"XAUUSD", "XAGUSD", "US100", "US30", "US500", "GER40", "UK100",
                        "USDJPY", "EURJPY", "GBPJPY", "AUDUSD", "GBPUSD", "EURUSD"}
        if symbol.upper() in _TREND_GUARD:
            last_h4 = h4.iloc[-1]
            if last_h4["ema_8"] > last_h4["ema_21"]:
                h4_ema_dir = 1
            elif last_h4["ema_8"] < last_h4["ema_21"]:
                h4_ema_dir = -1
            else:
                h4_ema_dir = 0
            if h4_ema_dir != 0 and ml_signal != h4_ema_dir:
                null_signal.reason = f"h4_ema_conflict(h4={h4_ema_dir},ml={ml_signal})"
                null_signal.ml_signal = ml_signal
                null_signal.ml_confidence = ml_conf
                return null_signal

        # H1 trend filter
        h1 = add_all_indicators(ohlcv["H1"])
        last_h1 = h1.iloc[-1]
        if last_h1["ema_8"] > last_h1["ema_21"] > last_h1["ema_50"]:
            h1_trend = 1
        elif last_h1["ema_8"] < last_h1["ema_21"] < last_h1["ema_50"]:
            h1_trend = -1
        else:
            h1_trend = 0

        # M5 ATR for SL/TP — floored to avoid stops collapsing to ~1 pip
        # during low-volatility periods (causes rapid repeated stop-outs)
        m5 = add_all_indicators(ohlcv["M5"])
        atr_val = float(m5["atr"].iloc[-1]) if not pd.isna(m5["atr"].iloc[-1]) else 0
        atr_val = max(atr_val, self._min_atr(symbol))

        # Confluence check (H4 ADX already confirmed ≥ 18 above).
        # Require explicit H1 agreement — a neutral H1 (no EMA stack) used to
        # pass through as "agreement", which let roughly half of all trades
        # through with no real multi-timeframe confirmation. Tightening this
        # cuts trade volume but raises the quality bar per entry.
        trend_agrees = h1_trend == ml_signal

        if not trend_agrees:
            return SignalResult(
                symbol=symbol, direction=0, confidence=0,
                ml_signal=ml_signal, ml_confidence=ml_conf,
                h1_trend=h1_trend, h4_adx=h4_adx,
                spread=spread, atr=atr_val, entry_price=entry,
                sl=0, tp=0, reason="h1_trend_conflict",
            )

        # Compute SL/TP using ATR
        decimals = self._price_decimals(symbol)
        if ml_signal == 1:
            sl = round(entry - self.atr_sl_mult * atr_val, decimals)
            tp = round(entry + self.atr_tp_mult * atr_val, decimals)
        else:
            sl = round(entry + self.atr_sl_mult * atr_val, decimals)
            tp = round(entry - self.atr_tp_mult * atr_val, decimals)

        # H1 agreement is mandatory above, so always apply the confluence boost.
        final_confidence = min(ml_conf * 1.1, 1.0)

        return SignalResult(
            symbol=symbol,
            direction=ml_signal,
            confidence=final_confidence,
            ml_signal=ml_signal,
            ml_confidence=ml_conf,
            h1_trend=h1_trend,
            h4_adx=h4_adx,
            spread=spread,
            atr=atr_val,
            entry_price=entry,
            sl=sl,
            tp=tp,
            reason="signal_confirmed",
        )
