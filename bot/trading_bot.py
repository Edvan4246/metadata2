"""
Main trading bot loop.

Cycle (every tick_interval seconds):
  1. Refresh OHLCV data for all symbols / timeframes
  2. For each symbol: generate signal → check risk → open position
  3. Update trailing stops on open positions
  4. Retrain ML models every retrain_interval cycles
  5. Broadcast state to WebSocket clients
"""
import asyncio
import logging
from datetime import datetime
from typing import Dict, List, Callable, Awaitable, Optional

from core.mt5_client import MT5Client
from core.data_fetcher import DataFetcher
from strategy.ml_model import ForexMLModel
from strategy.signal_generator import SignalGenerator
from strategy.types import SignalResult
from execution.order_manager import OrderManager
from risk.risk_manager import RiskManager
from config.settings import settings

logger = logging.getLogger(__name__)

TIMEFRAMES = ["M5", "M15", "H1", "H4"]


class TradingBot:
    def __init__(
        self,
        client: MT5Client,
        symbols: Optional[List[str]] = None,
        tick_interval: int = 60,
        retrain_interval: int = 500,
    ):
        self.client = client
        self.symbols = symbols or settings.symbols_list()
        self.tick_interval = tick_interval
        self.retrain_interval = retrain_interval

        self.fetcher = DataFetcher(client)
        self.risk_manager = RiskManager(
            max_open_positions=settings.max_open_positions,
            max_daily_drawdown=settings.max_daily_drawdown,
        )
        self.models: Dict[str, ForexMLModel] = {
            sym: ForexMLModel(sym) for sym in self.symbols
        }
        self.signal_gen = SignalGenerator(
            client=client,
            models=self.models,
            max_spread=settings.max_spread_points,
        )
        self.order_mgr = OrderManager(client, self.risk_manager)

        self._running = False
        self._cycle_count = 0
        self._last_signals: Dict[str, SignalResult] = {}
        self._state_callbacks: List[Callable[..., Awaitable]] = []

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self):
        logger.info("Starting trading bot | symbols=%s", self.symbols)
        if not self.client.connect():
            raise RuntimeError("Cannot connect to MT5")

        await self._bootstrap_models()
        self._running = True
        await self._loop()

    async def stop(self):
        logger.info("Stopping trading bot")
        self._running = False

    def register_state_callback(self, cb: Callable[..., Awaitable]):
        self._state_callbacks.append(cb)

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------

    async def _loop(self):
        while self._running:
            cycle_start = datetime.utcnow()
            try:
                await self._tick()
            except Exception as exc:
                logger.exception("Error in trading cycle: %s", exc)

            elapsed = (datetime.utcnow() - cycle_start).total_seconds()
            sleep_time = max(0, self.tick_interval - elapsed)
            await asyncio.sleep(sleep_time)

    async def _tick(self):
        self._cycle_count += 1

        # Refresh market data
        self.fetcher.refresh_all(self.symbols, TIMEFRAMES)

        # Periodic retrain
        if self._cycle_count % self.retrain_interval == 0:
            await self._retrain_models()

        # Process each symbol
        for symbol in self.symbols:
            ohlcv = self.fetcher.get_multi_tf(symbol)
            signal = self.signal_gen.generate(symbol, ohlcv)
            self._last_signals[symbol] = signal

            if signal.direction != 0:
                self.order_mgr.process_signal(signal)

            # Partial TP + break-even + trailing stop
            if signal.atr > 0:
                self.order_mgr.manage_open_positions(symbol, signal.atr)

        # Broadcast state
        state = self.get_state()
        for cb in self._state_callbacks:
            try:
                await cb(state)
            except Exception:
                pass

        logger.debug("Cycle %d complete", self._cycle_count)

    # ------------------------------------------------------------------
    # ML model management
    # ------------------------------------------------------------------

    async def _bootstrap_models(self):
        logger.info("Bootstrapping ML models…")
        for symbol in self.symbols:
            model = self.models[symbol]
            if not model.load():
                df = self.fetcher.refresh(symbol, "M5")
                if df is not None:
                    model.train(df)

    async def _retrain_models(self):
        logger.info("Retraining ML models…")
        for symbol in self.symbols:
            df = self.fetcher.get(symbol, "M5")
            if df is not None and len(df) >= 200:
                self.models[symbol].train(df)

    # ------------------------------------------------------------------
    # State snapshot (consumed by API + WebSocket)
    # ------------------------------------------------------------------

    def get_state(self) -> dict:
        account = self.client.get_account()
        positions = self.client.get_bot_positions()

        return {
            "running": self._running,
            "cycle": self._cycle_count,
            "timestamp": datetime.utcnow().isoformat(),
            "account": {
                "balance":    account.balance if account else 0,
                "equity":     account.equity  if account else 0,
                "free_margin": account.free_margin if account else 0,
                "currency":   account.currency if account else "USD",
            },
            "risk": self.risk_manager.status(),
            "positions": [
                {
                    "ticket":  p.ticket,
                    "symbol":  p.symbol,
                    "type":    p.type,
                    "volume":  p.volume,
                    "open":    p.price_open,
                    "current": p.price_current,
                    "sl":      p.sl,
                    "tp":      p.tp,
                    "profit":  p.profit,
                }
                for p in positions
            ],
            "signals": {
                sym: {
                    "direction":   s.direction,
                    "confidence":  round(s.confidence, 3),
                    "reason":      s.reason,
                    "h1_trend":    s.h1_trend,
                    "h4_adx":      round(s.h4_adx, 1),
                    "spread":      s.spread,
                }
                for sym, s in self._last_signals.items()
            },
        }
