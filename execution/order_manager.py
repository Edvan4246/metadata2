"""
Order lifecycle management — open, monitor trailing stop, close on signal reversal.
"""
import logging
from typing import Optional

from core.mt5_client import MT5Client, Position
from risk.position_sizing import calculate_lot_size
from risk.risk_manager import RiskManager
from strategy.signal_generator import SignalResult
from config.settings import settings

logger = logging.getLogger(__name__)


class OrderManager:
    def __init__(self, client: MT5Client, risk_manager: RiskManager):
        self.client = client
        self.risk_manager = risk_manager
        self.trailing_atr_mult = 1.0

    def process_signal(self, signal: SignalResult) -> Optional[int]:
        if signal.direction == 0:
            return None

        account = self.client.get_account()
        if account is None:
            logger.error("Cannot get account info")
            return None

        open_positions = self.client.get_bot_positions()
        can_open, reason = self.risk_manager.can_open(
            signal.symbol, open_positions, account.balance, account.equity
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
        )

        order_type = "buy" if signal.direction == 1 else "sell"
        result = self.client.open_position(
            symbol=signal.symbol,
            order_type=order_type,
            volume=lot,
            sl=signal.sl,
            tp=signal.tp,
            comment=f"bot_conf={signal.confidence:.2f}",
        )

        if result:
            logger.info(
                "Opened %s %s lot=%.2f conf=%.2f sl=%.5f tp=%.5f",
                order_type.upper(), signal.symbol, lot,
                signal.confidence, signal.sl, signal.tp,
            )
            return result.get("order")
        return None

    def update_trailing_stops(self, symbol: str, current_atr: float):
        positions = [p for p in self.client.get_bot_positions() if p.symbol == symbol]
        for pos in positions:
            new_sl = self._compute_trailing_sl(pos, current_atr)
            if new_sl and self._sl_improves(pos, new_sl):
                self.client.modify_sl_tp(pos.ticket, new_sl, pos.tp)

    def _compute_trailing_sl(self, pos: Position, atr: float) -> Optional[float]:
        trail = self.trailing_atr_mult * atr
        if pos.type == "buy":
            return round(pos.price_current - trail, 5)
        else:
            return round(pos.price_current + trail, 5)

    def _sl_improves(self, pos: Position, new_sl: float) -> bool:
        if pos.sl == 0:
            return True
        if pos.type == "buy":
            return new_sl > pos.sl
        return new_sl < pos.sl

    def close_all(self, symbol: Optional[str] = None):
        positions = self.client.get_bot_positions()
        if symbol:
            positions = [p for p in positions if p.symbol == symbol]
        for pos in positions:
            success = self.client.close_position(pos.ticket)
            if success:
                self.risk_manager.record_trade_closed(pos.profit)
                logger.info("Closed position %d profit=%.2f", pos.ticket, pos.profit)
