from __future__ import annotations

import pytest

from arbitrage_bot.models import OrderBook


def test_fill_buy_walks_multiple_levels():
    book = OrderBook(asks=[(100.0, 1.0), (101.0, 2.0)], bids=[])
    result = book.fill_buy(150.0)
    assert result is not None
    base_amount, avg_price = result
    assert base_amount == pytest.approx(1.0 + 50 / 101)
    assert avg_price == pytest.approx(150.0 / base_amount)


def test_fill_buy_insufficient_depth():
    book = OrderBook(asks=[(100.0, 1.0)], bids=[])
    assert book.fill_buy(1000.0) is None


def test_fill_sell_walks_multiple_levels():
    book = OrderBook(asks=[], bids=[(100.0, 1.0), (99.0, 2.0)])
    result = book.fill_sell(2.0)
    assert result is not None
    quote_received, avg_price = result
    assert quote_received == pytest.approx(1 * 100 + 1 * 99)
    assert avg_price == pytest.approx(quote_received / 2.0)


def test_fill_sell_insufficient_depth():
    book = OrderBook(asks=[], bids=[(100.0, 1.0)])
    assert book.fill_sell(5.0) is None
