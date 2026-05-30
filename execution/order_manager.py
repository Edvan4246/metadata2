"""
Order lifecycle management.

Features:
  - Open position with adaptive lot sizing based on signal confidence
  - Partial Take Profit: close 50% at 1R, move SL to break-even
  - Trailing stop (ATR-based) on remaining position
  - Close all on demand
"""
import logging
from dataclasses import dataclass, field
from typing import Optional, Dict

from core.mt5_client import MT5Client, Position
from risk.position_sizing import calculate_lot_size
from risk.risk_manager import RiskManager
from strategy.signal_generator import SignalResult
from config.settings import settings

logger = logging.getLogger(__name__)


@dataclass
class TradeState:
    """Tracks metadata for an open position to manage partial TP."""
    ticket: int
    entry_price: float
    sl_original: float
    tp_full: float
    direction: int
    partial_done: bool = False
    breakeven_set: bool = False


class OrderManager:
    def __init__(self, client: MT5Client, risk_manager: RiskManager,
                 trailing_atr_mult: float = 1.0,
                 partial_tp_ratio: float = 1.0):
        self.client = client
        self.risk_manager = risk_manager
        self.trailing_atr_mult = trailing_atr_mult
        # Close partial at partial_tp_ratio × (entry→SL distance) in the TP direction
        self.partial_tp_ratio = partial_tp_ratio
        self._states: Dict[int, TradeState] = {}  # ticket → state

    # ------------------------------------------------------------------
    # Open
    # ------------------------------------------------------------------

    def process_signal(self, signal: SignalResult) -> Optional[int]:
        if signal.direction == 0:
            return None

        account = self.client.get_account()
        if account is None:
            logger.error("Cannot get account info")
            return None

        open_positions = self.client.get_bot_positions()
        can_open, reason = self.risk_manager.can_open(
            signal.symbol, open_positions, account.balance, account.equity,
        )
        if not can_open:
            logger.debug("Signal rejected for %s: %s", signal.symbol, reason)
            return None

        lot = calculate_lot_size(
            equity=account.equity,
            risk_pct=settings.max_risk_per_trade,
            entry=signal.entry_price,
            sl=signal.sl,
            symbol=signal.symbol,
            confidence=signal.confidence,
        )

        order_type = "buy" if signal.direction == 1 else "sell"
        result = self.client.open_position(
            symbol=signal.symbol,
            order_type=order_type,
            volume=lot,
            sl=signal.sl,
            tp=signal.tp,
            comment=f"bot_{signal.reason[:12]}_c{signal.confidence:.2f}",
        )

        if result:
            ticket = result.get("order", 0)
            self._states[ticket] = TradeState(
                ticket=ticket,
                entry_price=signal.entry_price,
                sl_original=signal.sl,
                tp_full=signal.tp,
                direction=signal.direction,
            )
            logger.info(
                "Opened %s %s lot=%.2f conf=%.2f sl=%.5f tp=%.5f ticket=%d",
                order_type.upper(), signal.symbol, lot,
                signal.confidence, signal.sl, signal.tp, ticket,
            )
            return ticket
        return None

    # ------------------------------------------------------------------
    # Partial take profit + break-even
    # ------------------------------------------------------------------

    def manage_open_positions(self, symbol: str, current_atr: float):
        positions = [p for p in self.client.get_bot_positions() if p.symbol == symbol]

        for pos in positions:
            state = self._states.get(pos.ticket)
            if state is None:
                # Position opened outside this session; just trail
                self._update_trailing(pos, current_atr)
                continue

            sl_dist = abs(state.entry_price - state.sl_original)

            # Step 1 — Partial TP: close 50% when price moves 1R in our favour
            if not state.partial_done:
                profit_dist = self._profit_distance(pos)
                if profit_dist >= self.partial_tp_ratio * sl_dist:
                    self._close_partial(pos, ratio=0.5)
                    state.partial_done = True
                    logger.info(
                        "Partial TP taken on %s ticket=%d", symbol, pos.ticket
                    )

            # Step 2 — Move SL to break-even after partial TP
            if state.partial_done and not state.breakeven_set:
                be_sl = self._breakeven_sl(pos, current_atr)
                if self._sl_improves(pos, be_sl):
                    self.client.modify_sl_tp(pos.ticket, be_sl, pos.tp)
                    state.breakeven_set = True
                    logger.info(
                        "Break-even SL set on %s ticket=%d → %.5f",
                        symbol, pos.ticket, be_sl,
                    )

            # Step 3 — Trail remaining position
            if state.breakeven_set:
                self._update_trailing(pos, current_atr)

    # ------------------------------------------------------------------
    # Trailing stop
    # ------------------------------------------------------------------

    def _update_trailing(self, pos: Position, atr: float):
        new_sl = self._compute_trailing_sl(pos, atr)
        if new_sl and self._sl_improves(pos, new_sl):
            self.client.modify_sl_tp(pos.ticket, new_sl, pos.tp)

    def _compute_trailing_sl(self, pos: Position, atr: float) -> Optional[float]:
        trail = self.trailing_atr_mult * atr
        if pos.type == "buy":
            return round(pos.price_current - trail, 5)
        return round(pos.price_current + trail, 5)

    # ------------------------------------------------------------------
    # Close all
    # ------------------------------------------------------------------

    def close_all(self, symbol: Optional[str] = None):
        positions = self.client.get_bot_positions()
        if symbol:
            positions = [p for p in positions if p.symbol == symbol]
        for pos in positions:
            success = self.client.close_position(pos.ticket)
            if success:
                self.risk_manager.record_trade_closed(pos.profit)
                self._states.pop(pos.ticket, None)
                logger.info("Closed position %d profit=%.2f", pos.ticket, pos.profit)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _profit_distance(self, pos: Position) -> float:
        if pos.type == "buy":
            return pos.price_current - pos.price_open
        return pos.price_open - pos.price_current

    def _breakeven_sl(self, pos: Position, atr: float) -> float:
        # Break-even = entry ± small buffer (0.1 × ATR) so commission is covered
        buffer = 0.1 * atr
        if pos.type == "buy":
            return round(pos.price_open + buffer, 5)
        return round(pos.price_open - buffer, 5)

    def _sl_improves(self, pos: Position, new_sl: float) -> bool:
        if pos.sl == 0:
            return True
        return new_sl > pos.sl if pos.type == "buy" else new_sl < pos.sl

    def _close_partial(self, pos: Position, ratio: float = 0.5):
        partial_vol = round(pos.volume * ratio, 2)
        if partial_vol < 0.01:
            return
        # Reuse close_position logic via a temporary clone with reduced volume
        # MT5 supports partial close via the same close request with smaller volume
        if not hasattr(self.client, '_mt5_available') or not self.client._connected:
            logger.info("[SIM] Partial close %s ticket=%d vol=%.2f",
                        pos.symbol, pos.ticket, partial_vol)
            return
        # For live MT5, partial close is a sell/buy order with position=ticket and partial volume
        order_type = "sell" if pos.type == "buy" else "buy"
        self.client.open_position(
            symbol=pos.symbol,
            order_type=order_type,
            volume=partial_vol,
            sl=0,
            tp=0,
            comment="partial_tp",
        )
