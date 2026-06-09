"""
MT5 client wrapper — handles connection lifecycle, data retrieval, and order execution.
All public methods return None / empty structures on failure rather than raising,
so callers can decide how to handle unavailability (paper trading fallback, retry, etc.).
"""
import logging
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any

import pandas as pd
import numpy as np

logger = logging.getLogger(__name__)

try:
    import MetaTrader5 as mt5
    MT5_AVAILABLE = True
except ImportError:
    MT5_AVAILABLE = False
    logger.warning("MetaTrader5 package not installed — running in simulation mode")


@dataclass
class TickInfo:
    symbol: str
    bid: float
    ask: float
    spread: float
    time: pd.Timestamp


@dataclass
class AccountInfo:
    balance: float
    equity: float
    margin: float
    free_margin: float
    margin_level: float
    currency: str
    leverage: int


@dataclass
class Position:
    ticket: int
    symbol: str
    type: str          # "buy" | "sell"
    volume: float
    price_open: float
    price_current: float
    sl: float
    tp: float
    profit: float
    magic: int
    comment: str


class MT5Client:
    TIMEFRAME_MAP = {
        "M1":  1,
        "M5":  5,
        "M15": 15,
        "M30": 30,
        "H1":  60,
        "H4":  240,
        "D1":  1440,
    }

    def __init__(self, login: int, password: str, server: str, magic: int = 20240101):
        self.login = login
        self.password = password
        self.server = server
        self.magic = magic
        self._connected = False

    # ------------------------------------------------------------------
    # Connection
    # ------------------------------------------------------------------

    def connect(self) -> bool:
        if not MT5_AVAILABLE:
            logger.info("MT5 not available — simulation mode active")
            self._connected = True
            return True

        if not mt5.initialize():
            logger.error("mt5.initialize() failed: %s", mt5.last_error())
            return False

        if not mt5.login(self.login, self.password, self.server):
            logger.error("mt5.login() failed: %s", mt5.last_error())
            mt5.shutdown()
            return False

        info = mt5.account_info()
        logger.info(
            "Connected to MT5 | account=%s server=%s balance=%.2f %s",
            info.login, info.server, info.balance, info.currency,
        )
        self._connected = True
        return True

    def disconnect(self):
        if MT5_AVAILABLE and self._connected:
            mt5.shutdown()
        self._connected = False
        logger.info("MT5 disconnected")

    @contextmanager
    def session(self):
        try:
            if not self.connect():
                raise ConnectionError("Could not connect to MT5")
            yield self
        finally:
            self.disconnect()

    # ------------------------------------------------------------------
    # Market data
    # ------------------------------------------------------------------

    def get_tick(self, symbol: str) -> Optional[TickInfo]:
        if not MT5_AVAILABLE:
            return self._simulated_tick(symbol)

        tick = mt5.symbol_info_tick(symbol)
        if tick is None:
            return None
        spread = round((tick.ask - tick.bid) / mt5.symbol_info(symbol).point)
        return TickInfo(
            symbol=symbol,
            bid=tick.bid,
            ask=tick.ask,
            spread=spread,
            time=pd.Timestamp(tick.time, unit="s"),
        )

    def get_ohlcv(self, symbol: str, timeframe: str, count: int = 500) -> Optional[pd.DataFrame]:
        if not MT5_AVAILABLE:
            return self._simulated_ohlcv(symbol, timeframe, count)

        tf = self._resolve_timeframe(timeframe)
        if tf is None:
            return None

        rates = mt5.copy_rates_from_pos(symbol, tf, 0, count)
        if rates is None or len(rates) == 0:
            logger.warning("No rates for %s %s", symbol, timeframe)
            return None

        df = pd.DataFrame(rates)
        df["time"] = pd.to_datetime(df["time"], unit="s")
        df.set_index("time", inplace=True)
        df.rename(columns={"tick_volume": "volume"}, inplace=True)
        return df[["open", "high", "low", "close", "volume"]]

    # ------------------------------------------------------------------
    # Account
    # ------------------------------------------------------------------

    def get_account(self) -> Optional[AccountInfo]:
        if not MT5_AVAILABLE:
            return AccountInfo(10000, 10000, 0, 10000, 0, "USD", 100)

        info = mt5.account_info()
        if info is None:
            return None
        return AccountInfo(
            balance=info.balance,
            equity=info.equity,
            margin=info.margin,
            free_margin=info.margin_free,
            margin_level=info.margin_level,
            currency=info.currency,
            leverage=info.leverage,
        )

    # ------------------------------------------------------------------
    # Positions
    # ------------------------------------------------------------------

    def get_positions(self, symbol: Optional[str] = None) -> List[Position]:
        if not MT5_AVAILABLE:
            return []

        if symbol:
            raw = mt5.positions_get(symbol=symbol)
        else:
            raw = mt5.positions_get()

        if raw is None:
            return []

        return [
            Position(
                ticket=p.ticket,
                symbol=p.symbol,
                type="buy" if p.type == 0 else "sell",
                volume=p.volume,
                price_open=p.price_open,
                price_current=p.price_current,
                sl=p.sl,
                tp=p.tp,
                profit=p.profit,
                magic=p.magic,
                comment=p.comment,
            )
            for p in raw
        ]

    def get_bot_positions(self) -> List[Position]:
        return [p for p in self.get_positions() if p.magic == self.magic]

    # ------------------------------------------------------------------
    # Order execution
    # ------------------------------------------------------------------

    def open_position(
        self,
        symbol: str,
        order_type: str,
        volume: float,
        sl: float,
        tp: float,
        comment: str = "forex_bot",
    ) -> Optional[Dict[str, Any]]:
        if not MT5_AVAILABLE:
            logger.info(
                "[SIM] OPEN %s %s vol=%.2f sl=%.5f tp=%.5f",
                order_type.upper(), symbol, volume, sl, tp,
            )
            return {"retcode": 10009, "order": 0, "simulated": True}

        tick = mt5.symbol_info_tick(symbol)
        if tick is None:
            logger.error("Cannot get tick for %s", symbol)
            return None

        price = tick.ask if order_type == "buy" else tick.bid
        mt5_type = mt5.ORDER_TYPE_BUY if order_type == "buy" else mt5.ORDER_TYPE_SELL

        request = {
            "action":    mt5.TRADE_ACTION_DEAL,
            "symbol":    symbol,
            "volume":    volume,
            "type":      mt5_type,
            "price":     price,
            "sl":        sl,
            "tp":        tp,
            "deviation": 20,
            "magic":     self.magic,
            "comment":   comment,
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": self._get_filling_mode(symbol),
        }

        result = mt5.order_send(request)
        if result is None or result.retcode != mt5.TRADE_RETCODE_DONE:
            logger.error("order_send failed: %s", result)
            return None

        logger.info(
            "Opened %s %s ticket=%d vol=%.2f price=%.5f",
            order_type.upper(), symbol, result.order, volume, price,
        )
        return {"retcode": result.retcode, "order": result.order, "price": result.price}

    def close_position(self, ticket: int) -> bool:
        if not MT5_AVAILABLE:
            logger.info("[SIM] CLOSE ticket=%d", ticket)
            return True

        positions = mt5.positions_get(ticket=ticket)
        if not positions:
            logger.warning("Position %d not found", ticket)
            return False

        pos = positions[0]
        symbol = pos.symbol
        volume = pos.volume
        close_type = mt5.ORDER_TYPE_SELL if pos.type == 0 else mt5.ORDER_TYPE_BUY
        tick = mt5.symbol_info_tick(symbol)
        price = tick.bid if pos.type == 0 else tick.ask

        request = {
            "action":    mt5.TRADE_ACTION_DEAL,
            "symbol":    symbol,
            "volume":    volume,
            "type":      close_type,
            "position":  ticket,
            "price":     price,
            "deviation": 20,
            "magic":     self.magic,
            "comment":   "close",
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": self._get_filling_mode(symbol),
        }

        result = mt5.order_send(request)
        if result is None or result.retcode != mt5.TRADE_RETCODE_DONE:
            logger.error("close_position failed: %s", result)
            return False

        logger.info("Closed position ticket=%d", ticket)
        return True

    def get_position_profit(self, position_ticket: int) -> Optional[float]:
        """Sum the realized P&L for a position across all closing deals (handles partial closes)."""
        if not MT5_AVAILABLE:
            return None
        # Use a future ceiling so broker-timezone offsets (e.g. UTC+3) never
        # exclude deals that were just closed but appear "ahead" of VPS local time.
        to_dt = datetime.now() + timedelta(hours=24)
        from_dt = datetime.now() - timedelta(days=4)
        deals = mt5.history_deals_get(from_dt, to_dt)
        if deals is None:
            return None
        total = 0.0
        found = False
        for d in deals:
            # entry==1 → DEAL_ENTRY_OUT (closing deal); a position can have several
            # (partial TP + final close), so sum profit+swap+commission across all of them
            if d.position_id == position_ticket and d.entry == 1 and d.magic == self.magic:
                total += float(d.profit) + float(d.swap) + float(d.commission)
                found = True
        return total if found else None

    def modify_sl_tp(self, ticket: int, sl: float, tp: float) -> bool:
        if not MT5_AVAILABLE:
            logger.info("[SIM] MODIFY ticket=%d sl=%.5f tp=%.5f", ticket, sl, tp)
            return True

        request = {
            "action":   mt5.TRADE_ACTION_SLTP,
            "position": ticket,
            "sl":       sl,
            "tp":       tp,
        }
        result = mt5.order_send(request)
        return result is not None and result.retcode == mt5.TRADE_RETCODE_DONE

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _get_filling_mode(self, symbol: str):
        """Return the filling mode supported by the broker for this symbol.
        filling_mode bitmask: bit-0 = FOK allowed, bit-1 = IOC allowed."""
        info = mt5.symbol_info(symbol)
        if info is None:
            return mt5.ORDER_FILLING_FOK
        fm = info.filling_mode
        if fm & 1:   # FOK (Fill-or-Kill) supported
            return mt5.ORDER_FILLING_FOK
        if fm & 2:   # IOC (Immediate-or-Cancel) supported
            return mt5.ORDER_FILLING_IOC
        return mt5.ORDER_FILLING_RETURN

    def _resolve_timeframe(self, tf: str):
        if not MT5_AVAILABLE:
            return None
        mapping = {
            "M1":  mt5.TIMEFRAME_M1,
            "M5":  mt5.TIMEFRAME_M5,
            "M15": mt5.TIMEFRAME_M15,
            "M30": mt5.TIMEFRAME_M30,
            "H1":  mt5.TIMEFRAME_H1,
            "H4":  mt5.TIMEFRAME_H4,
            "D1":  mt5.TIMEFRAME_D1,
        }
        val = mapping.get(tf.upper())
        if val is None:
            logger.error("Unknown timeframe: %s", tf)
        return val

    # Simulation specs: (base_price, M5_return_std, candle_noise_pct, spread, ask_offset, decimals)
    # candle_noise_pct is the typical H-L range as % of price per M5 candle
    _SIM_SPECS = {
        # Forex
        "EURUSD": (1.08500, 0.00030, 0.00040, 15,   0.00015, 5),
        "GBPUSD": (1.27000, 0.00035, 0.00050, 18,   0.00018, 5),
        "USDJPY": (149.500, 0.00030, 0.00040, 12,   0.015,   3),
        "AUDUSD": (0.65000, 0.00028, 0.00038, 16,   0.00016, 5),
        "USDCAD": (1.36000, 0.00025, 0.00035, 18,   0.00018, 5),
        "USDCHF": (0.89000, 0.00025, 0.00035, 18,   0.00018, 5),
        "NZDUSD": (0.60000, 0.00028, 0.00038, 20,   0.00020, 5),
        "EURGBP": (0.85000, 0.00020, 0.00030, 15,   0.00015, 5),
        "EURJPY": (161.500, 0.00035, 0.00050, 18,   0.018,   3),
        "GBPJPY": (189.000, 0.00040, 0.00060, 25,   0.025,   3),
        # Metals
        "XAUUSD": (2350.00, 0.00025, 0.00060, 40,   0.40,    2),  # Gold
        "XAGUSD": (30.000,  0.00035, 0.00080, 60,   0.030,   3),  # Silver
        # US Indices
        "US100":  (19200.0, 0.00040, 0.00100, 2,    1.5,     1),  # Nasdaq 100
        "US30":   (39500.0, 0.00025, 0.00080, 3,    3.0,     1),  # Dow Jones 30
        "US500":  (5400.0,  0.00030, 0.00090, 1,    0.8,     1),  # S&P 500
        # EU/UK Indices
        "GER40":  (18200.0, 0.00030, 0.00090, 2,    2.0,     1),  # DAX 40
        "UK100":  (8200.0,  0.00025, 0.00070, 3,    1.5,     1),  # FTSE 100
    }
    _SIM_DEFAULT = (1.0, 0.00030, 0.00040, 15, 0.00015, 5)

    def _simulated_tick(self, symbol: str) -> TickInfo:
        base, _, _, spread, ask_offset, decimals = self._SIM_SPECS.get(
            symbol.upper(), self._SIM_DEFAULT
        )
        noise = np.random.uniform(-base * 0.0005, base * 0.0005)
        bid = round(base + noise, decimals)
        ask = round(bid + ask_offset, decimals)
        return TickInfo(symbol=symbol, bid=bid, ask=ask, spread=spread,
                        time=pd.Timestamp.now())

    def _simulated_ohlcv(self, symbol: str, timeframe: str, count: int) -> pd.DataFrame:
        np.random.seed(abs(hash(symbol + timeframe)) % 2**31)

        base, return_std, noise_pct, _, _, decimals = self._SIM_SPECS.get(
            symbol.upper(), self._SIM_DEFAULT
        )

        minutes = self.TIMEFRAME_MAP.get(timeframe.upper(), 60)
        # Scale volatility to timeframe (sqrt of bars per M5)
        tf_scale = np.sqrt(max(minutes, 1) / 5)
        scaled_std = return_std * tf_scale

        end = pd.Timestamp.now().floor(f"{minutes}min")
        index = pd.date_range(end=end, periods=count, freq=f"{minutes}min")

        returns = np.random.normal(0, scaled_std, count)
        close = base * np.exp(np.cumsum(returns))

        noise_abs = close * noise_pct * tf_scale
        noise_lo = np.random.uniform(0.3, 1.0, count) * noise_abs
        noise_hi = np.random.uniform(0.3, 1.0, count) * noise_abs

        opens = np.roll(close, 1)
        opens[0] = close[0]
        opens = opens * (1 + np.random.uniform(-return_std, return_std, count))

        df = pd.DataFrame({
            "open":   np.round(opens, decimals),
            "high":   np.round(close + noise_hi, decimals),
            "low":    np.round(close - noise_lo, decimals),
            "close":  np.round(close, decimals),
            "volume": np.random.randint(100, 5000, count).astype(float),
        }, index=index)
        return df
