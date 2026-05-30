"""
Multi-timeframe data manager — caches OHLCV frames per symbol/timeframe,
refreshes on-demand, and exposes a unified interface to the strategy layer.
"""
import logging
from typing import Dict, Optional, Tuple
from datetime import datetime

import pandas as pd

from core.mt5_client import MT5Client

logger = logging.getLogger(__name__)

# Candles kept in memory per symbol/timeframe
CACHE_DEPTH = {
    "M5":  500,
    "M15": 300,
    "H1":  200,
    "H4":  100,
}


class DataFetcher:
    def __init__(self, client: MT5Client):
        self.client = client
        self._cache: Dict[Tuple[str, str], pd.DataFrame] = {}
        self._last_refresh: Dict[Tuple[str, str], datetime] = {}

    def refresh(self, symbol: str, timeframe: str) -> Optional[pd.DataFrame]:
        count = CACHE_DEPTH.get(timeframe, 300)
        df = self.client.get_ohlcv(symbol, timeframe, count)
        if df is not None and not df.empty:
            self._cache[(symbol, timeframe)] = df
            self._last_refresh[(symbol, timeframe)] = datetime.utcnow()
        return df

    def get(self, symbol: str, timeframe: str) -> Optional[pd.DataFrame]:
        key = (symbol, timeframe)
        if key not in self._cache:
            return self.refresh(symbol, timeframe)
        return self._cache[key]

    def refresh_all(self, symbols: list, timeframes: list):
        for sym in symbols:
            for tf in timeframes:
                self.refresh(sym, tf)
        logger.debug("Refreshed %d symbol-timeframe pairs", len(symbols) * len(timeframes))

    def get_multi_tf(self, symbol: str) -> Dict[str, pd.DataFrame]:
        result = {}
        for tf in CACHE_DEPTH:
            df = self.get(symbol, tf)
            if df is not None:
                result[tf] = df
        return result

    def last_close(self, symbol: str, timeframe: str = "M5") -> Optional[float]:
        df = self.get(symbol, timeframe)
        if df is None or df.empty:
            return None
        return float(df["close"].iloc[-1])
