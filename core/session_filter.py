"""
Trading session filter.

Only trade during high-liquidity windows where spread is tight and
volume patterns are more predictable. Times in UTC.

Sessions:
  London:    07:00–12:00 UTC  (08:00–13:00 BRT)
  New York:  13:00–21:00 UTC  (10:00–18:00 BRT)
  Overlap:   13:00–16:00 UTC  (best window for forex)

Per-instrument restrictions:
  Forex pairs : London + NY
  XAUUSD      : London + NY (most active)
  US100/US30  : NY only (US market hours)
  Asian pairs : include Tokyo 00:00–09:00 UTC
"""
from datetime import time, datetime, timezone
from typing import Optional


# (start_utc, end_utc) pairs
SESSIONS = {
    "tokyo":   (time(0,  0), time(9,  0)),
    "london":  (time(7,  0), time(12, 0)),
    "ny":      (time(13, 0), time(21, 0)),
    "overlap": (time(13, 0), time(16, 0)),
}

# Which sessions each symbol can trade in
SYMBOL_SESSIONS: dict[str, list[str]] = {
    # US indices — only NY market hours
    "US100": ["ny"],
    "US30":  ["ny"],
    "US500": ["ny"],
    # Gold — London and NY
    "XAUUSD": ["london", "ny"],
    "XAGUSD": ["london", "ny"],
    # Asian pairs — JPY pairs only in Tokyo (not AUD/NZD — ML trained on London/NY)
    "USDJPY": ["tokyo", "london", "ny"],
    "EURJPY": ["tokyo", "london", "ny"],
    "GBPJPY": ["tokyo", "london", "ny"],
    "AUDJPY": ["tokyo", "london", "ny"],
    "AUDUSD": ["london", "ny"],
    "NZDUSD": ["london", "ny"],
}
DEFAULT_SESSIONS = ["london", "ny"]    # all other forex pairs

# Crypto trades 24/7 — no session or weekend restrictions
CRYPTO_SYMBOLS = {"BTCUSD", "ETHUSD"}


def _in_session(now_utc: time, start: time, end: time) -> bool:
    if start <= end:
        return start <= now_utc < end
    # overnight wrap (e.g. 22:00–02:00)
    return now_utc >= start or now_utc < end


def is_tradeable(symbol: str, dt: Optional[datetime] = None) -> bool:
    """Return True if symbol should be traded at the given UTC datetime."""
    if dt is None:
        dt = datetime.now(timezone.utc)

    if symbol.upper() in CRYPTO_SYMBOLS:
        return True

    now_t = dt.time()

    # Never trade Friday 21:00 UTC to Sunday 22:00 UTC (weekend gaps)
    weekday = dt.weekday()   # 0=Mon … 6=Sun
    if weekday == 4 and now_t >= time(21, 0):   # Friday evening
        return False
    if weekday == 5:                              # Saturday
        return False
    if weekday == 6 and now_t < time(22, 0):    # Sunday pre-open
        return False

    sym_sessions = SYMBOL_SESSIONS.get(symbol.upper(), DEFAULT_SESSIONS)
    return any(
        _in_session(now_t, *SESSIONS[s])
        for s in sym_sessions
    )


def session_name(dt: Optional[datetime] = None) -> str:
    """Return a human-readable label for the current session."""
    if dt is None:
        dt = datetime.now(timezone.utc)
    now_t = dt.time()
    if _in_session(now_t, *SESSIONS["overlap"]):
        return "London/NY Overlap"
    if _in_session(now_t, *SESSIONS["london"]):
        return "London"
    if _in_session(now_t, *SESSIONS["ny"]):
        return "New York"
    if _in_session(now_t, *SESSIONS["tokyo"]):
        return "Tokyo"
    return "Off-Hours"
