from __future__ import annotations

from arbitrage_bot.detectors import triangular
from arbitrage_bot.models import Ticker


def test_finds_profitable_triangle():
    # USDT -> BTC -> ETH -> USDT with a deliberate mispricing and no fees.
    tickers = {
        "BTC/USDT": Ticker(bid=20000, ask=20010),
        "ETH/USDT": Ticker(bid=1000, ask=1001),
        "ETH/BTC": Ticker(bid=0.049, ask=0.0491),  # ETH cheap in BTC terms -> profit
    }
    opps = triangular.find_opportunities(tickers, base="USDT", alts=["BTC", "ETH"], fee_pct=0.0)
    assert any(o.net_profit_pct > 0 for o in opps)


def test_fees_can_erase_triangular_profit():
    tickers = {
        "BTC/USDT": Ticker(bid=20000, ask=20010),
        "ETH/USDT": Ticker(bid=1000, ask=1001),
        "ETH/BTC": Ticker(bid=0.049, ask=0.0491),
    }
    opps = triangular.find_opportunities(tickers, base="USDT", alts=["BTC", "ETH"], fee_pct=0.05)
    assert opps == []


def test_no_opportunity_without_required_markets():
    tickers = {"BTC/USDT": Ticker(bid=20000, ask=20010)}
    opps = triangular.find_opportunities(tickers, base="USDT", alts=["BTC", "ETH"], fee_pct=0.001)
    assert opps == []
