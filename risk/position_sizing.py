"""
Position sizing strategies.

Default: fixed-fractional risk model (risk X% of equity per trade).
SL distance in price → lot size calculation via pip/point value.

Supports forex pairs, gold (XAUUSD), and indices (US100, US30).

Formula:
  risk_amount      = equity * risk_pct
  pip_value_per_lot = point_size * contract_size  (or dynamic for JPY)
  lots = risk_amount / (sl_points * pip_value_per_lot)
"""
import logging

logger = logging.getLogger(__name__)

# Per-instrument specs: (point_size, pip_value_per_lot_USD)
# pip_value_per_lot = USD earned/lost per 1 point move on 1.0 lot
# For JPY pairs pip_value_per_lot is None → computed dynamically from price
INSTRUMENT_SPECS: dict[str, tuple[float, float | None]] = {
    # Forex — JPY pairs (dynamic pip value)
    "USDJPY": (0.01,    None),
    "EURJPY": (0.01,    None),
    "GBPJPY": (0.01,    None),
    "AUDJPY": (0.01,    None),
    "CADJPY": (0.01,    None),
    "CHFJPY": (0.01,    None),
    "NZDJPY": (0.01,    None),
    # Metals
    "XAUUSD": (0.01,    1.0),    # Gold: 1 lot=100oz, $0.01 move = $1
    "XAGUSD": (0.001,   50.0),   # Silver
    # US Indices (retail standard: 1 lot = 1 contract, $1/point)
    # Note: multiply pip_value_per_lot by your broker's contract multiplier if needed
    "US100":  (1.0,     1.0),    # Nasdaq 100
    "US30":   (1.0,     1.0),    # Dow Jones 30
    "US500":  (1.0,     1.0),    # S&P 500
    # EU/UK Indices
    "GER40":  (1.0,     1.0),    # DAX 40
    "UK100":  (1.0,     1.0),    # FTSE 100
    # Crypto CFDs
    "BTCUSD": (1.0,     1.0),
    "ETHUSD": (0.01,    1.0),
}

# Default for unlisted forex pairs
_DEFAULT_SPEC: tuple[float, float | None] = (0.0001, 10.0)  # 1 pip = $10/lot
_FOREX_CONTRACT_SIZE = 100_000

MIN_LOT = 0.01
MAX_LOT = 10.0


def adaptive_risk_pct(base_risk: float, confidence: float) -> float:
    """Scale risk between 0.75× and 1.5× base based on ML confidence."""
    if confidence >= 0.75:
        return base_risk * 1.5    # high confidence → bigger size
    if confidence >= 0.65:
        return base_risk * 1.2
    if confidence >= 0.55:
        return base_risk * 1.0
    return base_risk * 0.75       # low confidence → smaller size


def calculate_lot_size(
    equity: float,
    risk_pct: float,
    entry: float,
    sl: float,
    symbol: str,
    confidence: float = 0.60,
    min_lot: float = MIN_LOT,
    max_lot: float = MAX_LOT,
) -> float:
    risk_pct = adaptive_risk_pct(risk_pct, confidence)
    sym = symbol.upper().replace(".", "").replace("-", "")
    point_size, pip_value_per_lot = INSTRUMENT_SPECS.get(sym, _DEFAULT_SPEC)

    sl_distance = abs(entry - sl)
    sl_points = sl_distance / point_size

    if sl_points <= 0:
        logger.warning("SL distance is zero for %s — using min lot", symbol)
        return min_lot

    risk_amount = equity * risk_pct

    # JPY pairs: pip value depends on current price
    if pip_value_per_lot is None:
        pip_value_per_lot = (point_size / entry) * _FOREX_CONTRACT_SIZE

    lots = risk_amount / (sl_points * pip_value_per_lot)
    lots = max(min_lot, min(max_lot, round(lots, 2)))

    logger.debug(
        "%s sizing: equity=%.2f risk=%.1f%% sl_pts=%.1f pip_val=%.2f → lots=%.2f",
        symbol, equity, risk_pct * 100, sl_points, pip_value_per_lot, lots,
    )
    return lots


def kelly_criterion(win_rate: float, avg_win: float, avg_loss: float) -> float:
    """Kelly fraction — cap at 25% to limit over-betting."""
    if avg_loss <= 0 or win_rate <= 0:
        return 0.01
    odds = avg_win / avg_loss
    kelly = win_rate - (1 - win_rate) / odds
    return max(0.0, min(0.25, kelly))
