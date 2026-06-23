from __future__ import annotations

from itertools import permutations

from arbitrage_bot.models import Opportunity, Ticker


def _convert(amount: float, tickers: dict[str, Ticker], from_ccy: str, to_ccy: str, fee_pct: float) -> float | None:
    """Convert `amount` of from_ccy into to_ccy using the best available market,
    applying the taker fee. Returns None if no direct market exists."""
    direct = f"{from_ccy}/{to_ccy}"
    inverse = f"{to_ccy}/{from_ccy}"

    if direct in tickers:
        # selling from_ccy for to_ccy at the bid price
        converted = amount * tickers[direct].bid
    elif inverse in tickers:
        # buying to_ccy with from_ccy at the ask price
        converted = amount / tickers[inverse].ask
    else:
        return None

    return converted * (1 - fee_pct)


def find_opportunities(
    tickers: dict[str, Ticker],
    base: str,
    alts: list[str],
    fee_pct: float,
) -> list[Opportunity]:
    """Scans BASE -> X -> Y -> BASE triangles among the given alt currencies."""
    opportunities: list[Opportunity] = []

    for x, y in permutations(alts, 2):
        amount = 1.0
        leg1 = _convert(amount, tickers, base, x, fee_pct)
        if leg1 is None:
            continue
        leg2 = _convert(leg1, tickers, x, y, fee_pct)
        if leg2 is None:
            continue
        final = _convert(leg2, tickers, y, base, fee_pct)
        if final is None:
            continue

        net_profit_pct = final - 1.0
        gross_profit_pct = net_profit_pct + 3 * fee_pct  # approx fees removed

        if net_profit_pct > 0:
            opportunities.append(
                Opportunity(
                    kind="triangular",
                    description=f"{base} -> {x} -> {y} -> {base}",
                    net_profit_pct=net_profit_pct,
                    gross_profit_pct=gross_profit_pct,
                    details={"base": base, "x": x, "y": y},
                )
            )

    opportunities.sort(key=lambda o: o.net_profit_pct, reverse=True)
    return opportunities
