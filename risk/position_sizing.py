"""
Position sizing strategies.

Default: fixed-fractional risk model (risk X% of equity per trade).
SL distance in price → lot size calculation via pip value.

Formula:
  risk_amount = equity * risk_pct
  pip_value   = (pip_size / price) * lot_size * contract_size
  lots = risk_amount / (sl_pips * pip_value_per_lot)
"""
import logging
from typing import Optional

logger = logging.getLogger(__name__)

# Standard contract sizes and pip sizes per symbol group
PIP_SIZE = {
    "USDJPY": 0.01, "EURJPY": 0.01, "GBPJPY": 0.01,
    "AUDJPY": 0.01, "CADJPY": 0.01, "CHFJPY": 0.01,
}
DEFAULT_PIP_SIZE = 0.0001

CONTRACT_SIZE = 100_000   # standard lot
MIN_LOT = 0.01
MAX_LOT = 10.0


def calculate_lot_size(
    equity: float,
    risk_pct: float,
    entry: float,
    sl: float,
    symbol: str,
    min_lot: float = MIN_LOT,
    max_lot: float = MAX_LOT,
) -> float:
    pip_size = PIP_SIZE.get(symbol[:6].upper(), DEFAULT_PIP_SIZE)
    sl_distance = abs(entry - sl)
    sl_pips = sl_distance / pip_size

    if sl_pips <= 0:
        logger.warning("SL distance is zero for %s — using min lot", symbol)
        return min_lot

    risk_amount = equity * risk_pct

    # Pip value per 1.0 lot in account currency (approx for USD accounts)
    if symbol.endswith("JPY"):
        pip_value_per_lot = (pip_size / entry) * CONTRACT_SIZE
    else:
        pip_value_per_lot = pip_size * CONTRACT_SIZE

    lots = risk_amount / (sl_pips * pip_value_per_lot)
    lots = max(min_lot, min(max_lot, round(lots, 2)))

    logger.debug(
        "%s sizing: equity=%.2f risk=%.1f%% sl_pips=%.1f → lots=%.2f",
        symbol, equity, risk_pct * 100, sl_pips, lots,
    )
    return lots


def kelly_criterion(win_rate: float, avg_win: float, avg_loss: float) -> float:
    """Kelly fraction — cap at 25% to limit over-betting."""
    if avg_loss <= 0 or win_rate <= 0:
        return 0.01
    odds = avg_win / avg_loss
    kelly = win_rate - (1 - win_rate) / odds
    return max(0.0, min(0.25, kelly))
