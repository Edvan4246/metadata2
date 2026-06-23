from __future__ import annotations

from arbitrage_bot.detectors import cross_exchange
from arbitrage_bot.models import Ticker


def test_finds_opportunity_across_two_exchanges():
    exchange_tickers = {
        "binance": {"BTC/USDT": Ticker(bid=19900, ask=19950)},
        "kraken": {"BTC/USDT": Ticker(bid=20100, ask=20150)},
    }
    opps = cross_exchange.find_opportunities(exchange_tickers, symbols=["BTC/USDT"], fee_pct=0.0)
    assert len(opps) == 1
    opp = opps[0]
    assert opp.details["buy_exchange"] == "binance"
    assert opp.details["sell_exchange"] == "kraken"
    assert opp.net_profit_pct > 0


def test_no_opportunity_with_single_exchange():
    exchange_tickers = {"binance": {"BTC/USDT": Ticker(bid=19900, ask=19950)}}
    opps = cross_exchange.find_opportunities(exchange_tickers, symbols=["BTC/USDT"], fee_pct=0.0)
    assert opps == []


def test_fees_can_erase_cross_exchange_profit():
    exchange_tickers = {
        "binance": {"BTC/USDT": Ticker(bid=19900, ask=19950)},
        "kraken": {"BTC/USDT": Ticker(bid=20100, ask=20150)},
    }
    opps = cross_exchange.find_opportunities(exchange_tickers, symbols=["BTC/USDT"], fee_pct=0.01)
    assert opps == []
