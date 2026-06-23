from __future__ import annotations

import pytest

from arbitrage_bot import depth_check
from arbitrage_bot.models import OrderBook


def test_validate_cross_exchange_profitable_with_enough_depth():
    buy_book = OrderBook(asks=[(19900.0, 5.0)], bids=[])
    sell_book = OrderBook(asks=[], bids=[(20100.0, 5.0)])

    fill = depth_check.validate_cross_exchange(buy_book, sell_book, trade_size_quote=1000.0, fee_pct=0.0)

    assert fill is not None
    assert fill.net_profit_pct == pytest.approx((20100.0 - 19900.0) / 19900.0)
    assert fill.base_amount == pytest.approx(1000.0 / 19900.0)
    assert fill.quote_received == pytest.approx(fill.base_amount * 20100.0)


def test_validate_cross_exchange_insufficient_depth_on_buy_side():
    buy_book = OrderBook(asks=[(19900.0, 0.001)], bids=[])
    sell_book = OrderBook(asks=[], bids=[(20100.0, 5.0)])

    fill = depth_check.validate_cross_exchange(buy_book, sell_book, trade_size_quote=1000.0, fee_pct=0.0)

    assert fill is None


def test_validate_cross_exchange_fees_can_erase_profit():
    buy_book = OrderBook(asks=[(19900.0, 5.0)], bids=[])
    sell_book = OrderBook(asks=[], bids=[(20100.0, 5.0)])

    fill = depth_check.validate_cross_exchange(buy_book, sell_book, trade_size_quote=1000.0, fee_pct=0.01)

    assert fill is not None
    assert fill.net_profit_pct < 0


def test_validate_triangular_profitable():
    books = {
        "BTC/USDT": OrderBook(asks=[(20010.0, 10.0)], bids=[(20000.0, 10.0)]),
        "ETH/USDT": OrderBook(asks=[(1001.0, 100.0)], bids=[(1000.0, 100.0)]),
        "ETH/BTC": OrderBook(asks=[(0.0491, 1000.0)], bids=[(0.049, 1000.0)]),
    }

    net = depth_check.validate_triangular("USDT", "BTC", "ETH", 1000.0, books, fee_pct=0.0)

    assert net is not None
    assert net > 0


def test_validate_triangular_missing_market_returns_none():
    books = {"BTC/USDT": OrderBook(asks=[(20010.0, 10.0)], bids=[(20000.0, 10.0)])}

    net = depth_check.validate_triangular("USDT", "BTC", "ETH", 1000.0, books, fee_pct=0.0)

    assert net is None
