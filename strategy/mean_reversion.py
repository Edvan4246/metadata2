"""
Mean-reversion strategy — activated when ADX < 18 (ranging market).

Entry logic:
  BUY  when: price touches or breaks below BB lower band
             AND RSI < 35 (oversold)
             AND Stochastic K < 25
  SELL when: price touches or breaks above BB upper band
             AND RSI > 65 (overbought)
             AND Stochastic K > 75

Exit:
  TP = BB middle band (mean)
  SL = entry ± (1.2 × ATR)   — tighter than trend strategy

This complements the trend strategy by capturing the ~40% of time
the market spends in consolidation/range.
"""
import logging
from typing import Optional

import pandas as pd

from strategy.indicators import add_all_indicators
from strategy.types import SignalResult

logger = logging.getLogger(__name__)

# Thresholds
RSI_OVERSOLD  = 35
RSI_OVERBOUGHT = 65
STOCH_OVERSOLD = 25
STOCH_OVERBOUGHT = 75
ATR_SL_MULT   = 1.2    # tighter SL for mean-reversion


def generate_mean_reversion_signal(
    symbol: str,
    ohlcv: dict,
    entry_price: float,
    spread: float,
    max_spread: int,
    h4_adx: float,
    price_decimals: int = 5,
) -> Optional[SignalResult]:
    """
    Returns a SignalResult if a mean-reversion entry is found, else None.
    Called when H4 ADX < 18 (the regime check already happened in the caller —
    h4_adx is passed through only to populate the SignalResult).
    """
    if "M5" not in ohlcv:
        return None

    df = add_all_indicators(ohlcv["M5"])
    last = df.iloc[-1]

    rsi     = last.get("rsi", 50)
    stoch_k = last.get("stoch_k", 50)
    close   = last.get("close", entry_price)
    bb_low  = last.get("bb_lower", 0)
    bb_up   = last.get("bb_upper", 0)
    bb_mid  = last.get("bb_mid", close)
    atr     = last.get("atr", 0)

    if pd.isna(rsi) or pd.isna(atr) or atr == 0:
        return None

    direction = 0
    reason    = ""

    # BUY signal: price at/below lower BB + oversold
    if (close <= bb_low * 1.001
            and rsi < RSI_OVERSOLD
            and stoch_k < STOCH_OVERSOLD):
        direction = 1
        reason = f"mr_oversold(rsi={rsi:.1f},stoch={stoch_k:.1f})"

    # SELL signal: price at/above upper BB + overbought
    elif (close >= bb_up * 0.999
            and rsi > RSI_OVERBOUGHT
            and stoch_k > STOCH_OVERBOUGHT):
        direction = -1
        reason = f"mr_overbought(rsi={rsi:.1f},stoch={stoch_k:.1f})"

    if direction == 0:
        return None

    if spread > max_spread:
        return None

    # SL: outside ATR from entry
    if direction == 1:
        sl = round(entry_price - ATR_SL_MULT * atr, price_decimals)
        tp = round(bb_mid, price_decimals)    # TP at mean
    else:
        sl = round(entry_price + ATR_SL_MULT * atr, price_decimals)
        tp = round(bb_mid, price_decimals)

    # Confidence is fixed for MR signals (simpler model)
    confidence = 0.60

    logger.debug("MR signal %s %s conf=%.2f", "BUY" if direction == 1 else "SELL", symbol, confidence)

    return SignalResult(
        symbol=symbol,
        direction=direction,
        confidence=confidence,
        ml_signal=direction,
        ml_confidence=confidence,
        h1_trend=0,
        h4_adx=h4_adx,
        spread=spread,
        atr=float(atr),
        entry_price=entry_price,
        sl=sl,
        tp=tp,
        reason=reason,
    )
