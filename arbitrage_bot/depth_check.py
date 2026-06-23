from __future__ import annotations

from arbitrage_bot.models import OrderBook


def validate_cross_exchange(
    buy_book: OrderBook,
    sell_book: OrderBook,
    trade_size_quote: float,
    fee_pct: float,
) -> float | None:
    """Re-simulates an opportunity using real order book depth instead of best
    bid/ask, for a trade of `trade_size_quote` units of quote currency.

    Returns the realistic net profit pct, or None if either leg's book doesn't
    have enough depth to fill the trade without excessive slippage.
    """
    bought = buy_book.fill_buy(trade_size_quote)
    if bought is None:
        return None
    base_amount, _ = bought

    sold = sell_book.fill_sell(base_amount)
    if sold is None:
        return None
    quote_received, _ = sold

    gross_profit_pct = (quote_received - trade_size_quote) / trade_size_quote
    return gross_profit_pct - 2 * fee_pct


def _convert_with_depth(
    amount: float,
    books: dict[str, OrderBook],
    from_ccy: str,
    to_ccy: str,
    fee_pct: float,
) -> float | None:
    direct = f"{from_ccy}/{to_ccy}"
    inverse = f"{to_ccy}/{from_ccy}"

    if direct in books:
        result = books[direct].fill_sell(amount)
    elif inverse in books:
        result = books[inverse].fill_buy(amount)
    else:
        return None

    if result is None:
        return None
    converted, _ = result
    return converted * (1 - fee_pct)


def validate_triangular(
    base: str,
    x: str,
    y: str,
    amount_base_currency: float,
    books: dict[str, OrderBook],
    fee_pct: float,
) -> float | None:
    """Re-simulates a BASE -> X -> Y -> BASE triangle using real order book
    depth for a trade of `amount_base_currency` units of the account's base
    currency. Returns None if any leg lacks the market or the depth to fill.
    """
    leg1 = _convert_with_depth(amount_base_currency, books, base, x, fee_pct)
    if leg1 is None:
        return None
    leg2 = _convert_with_depth(leg1, books, x, y, fee_pct)
    if leg2 is None:
        return None
    final = _convert_with_depth(leg2, books, y, base, fee_pct)
    if final is None:
        return None
    return (final - amount_base_currency) / amount_base_currency
