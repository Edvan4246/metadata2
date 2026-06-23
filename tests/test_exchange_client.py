from __future__ import annotations

from unittest.mock import MagicMock

from arbitrage_bot.exchange_client import ExchangeClient


def _client_with_fake_exchange(markets: dict, order_book: dict) -> ExchangeClient:
    client = ExchangeClient.__new__(ExchangeClient)
    client.exchange_id = "fake"
    client.exchange = MagicMock()
    client.exchange.markets = markets
    client.exchange.fetch_order_book.return_value = order_book
    return client


def test_fetch_order_book_parses_ccxt_levels():
    client = _client_with_fake_exchange(
        markets={"BTC/USDT": {}},
        order_book={
            "asks": [[20010.0, 1.5], [20011.0, 2.0]],
            "bids": [[20000.0, 1.0], [19999.0, 3.0]],
        },
    )

    book = client.fetch_order_book("BTC/USDT")

    assert book is not None
    assert book.asks == [(20010.0, 1.5), (20011.0, 2.0)]
    assert book.bids == [(20000.0, 1.0), (19999.0, 3.0)]


def test_fetch_order_book_returns_none_for_unknown_symbol():
    client = _client_with_fake_exchange(markets={}, order_book={"asks": [], "bids": []})

    assert client.fetch_order_book("BTC/USDT") is None


def test_fetch_order_book_returns_none_when_book_is_empty():
    client = _client_with_fake_exchange(
        markets={"BTC/USDT": {}},
        order_book={"asks": [], "bids": [[19999.0, 3.0]]},
    )

    assert client.fetch_order_book("BTC/USDT") is None
