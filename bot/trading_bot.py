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
import os
import time
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
        retrain_interval: int = 150,
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
        self._known_tickets: Dict[int, dict] = {}    # ticket → {symbol, type, volume, open, profit}
        self._closed_trades: list = []               # history for dashboard

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

        # Detect positions closed by MT5 (SL/TP hit) since last cycle
        self._sync_closed_positions()

        # Process each symbol
        for symbol in self.symbols:
            ohlcv = self.fetcher.get_multi_tf(symbol)
            signal = self.signal_gen.generate(symbol, ohlcv)
            self._last_signals[symbol] = signal

            if signal.direction != 0:
                new_ticket = self.order_mgr.process_signal(signal)
                if new_ticket is not None:
                    self._register_new_ticket(new_ticket)

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
        """Load saved models; force retrain any model older than 8 hours."""
        logger.info("Bootstrapping ML models…")
        max_age_secs = 8 * 3600
        for symbol in self.symbols:
            model = self.models[symbol]
            model_path = os.path.join("models", f"{symbol}.pkl")
            stale = True
            if os.path.exists(model_path):
                age = time.time() - os.path.getmtime(model_path)
                stale = age > max_age_secs
            if not stale and model.load():
                continue
            logger.info("Retraining %s (model %s)", symbol,
                        "stale" if stale else "missing")
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
    # Closed-position sync (detect SL/TP hits)
    # ------------------------------------------------------------------

    def _register_new_ticket(self, ticket: int):
        """Track a just-opened position immediately so that, even if it closes
        again before the next cycle (fast SL/TP hit), _sync_closed_positions
        still detects and records it instead of silently dropping it."""
        if ticket in self._known_tickets:
            return
        for p in self.client.get_bot_positions():
            if p.ticket == ticket:
                self._known_tickets[ticket] = {
                    "symbol": p.symbol,
                    "type":   p.type,
                    "volume": p.volume,
                    "open":   p.price_open,
                    "profit": p.profit,
                }
                break

    def _sync_closed_positions(self):
        """Detect positions closed by MT5 (SL/TP) since last tick and record them."""
        current = {p.ticket: p for p in self.client.get_bot_positions()}
        closed_tickets = set(self._known_tickets) - set(current)

        for ticket in closed_tickets:
            info = self._known_tickets[ticket]
            # Try MT5 history first; fall back to last-known floating P&L
            profit = self.client.get_position_profit(ticket)
            if profit is None:
                profit = info.get("profit", 0.0)

            self.risk_manager.record_trade_closed(profit)
            self._closed_trades.append({
                "ticket":    ticket,
                "symbol":    info["symbol"],
                "type":      info["type"],
                "volume":    info["volume"],
                "open":      info["open"],
                "profit":    round(profit, 2),
                "closed_at": datetime.utcnow().isoformat(),
            })
            self.order_mgr._states.pop(ticket, None)
            logger.info(
                "Closed by MT5 | ticket=%d symbol=%s profit=%.2f",
                ticket, info["symbol"], profit,
            )

        # Update known-tickets map to current open positions
        self._known_tickets = {
            t: {
                "symbol": p.symbol,
                "type":   p.type,
                "volume": p.volume,
                "open":   p.price_open,
                "profit": p.profit,
            }
            for t, p in current.items()
        }

        # Cap history at 100 trades to avoid unbounded growth
        if len(self._closed_trades) > 100:
            self._closed_trades = self._closed_trades[-100:]

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
            "closed_trades": list(reversed(self._closed_trades[-20:])),
        }
