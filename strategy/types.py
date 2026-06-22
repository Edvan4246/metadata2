from dataclasses import dataclass


@dataclass
class SignalResult:
    symbol: str
    direction: int          # 1=BUY, -1=SELL, 0=HOLD
    confidence: float       # 0-1
    ml_signal: int
    ml_confidence: float
    h1_trend: int           # 1=up, -1=down, 0=neutral
    h4_adx: float
    spread: float
    atr: float
    entry_price: float
    sl: float
    tp: float
    reason: str
