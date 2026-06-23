from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ExchangeBalances:
    """Tracks currency pre-positioned on each exchange for cross-exchange arbitrage.

    Real cross-exchange arbitrage can't wait for an on-chain transfer mid-trade:
    you buy the base asset where it's cheap using quote currency you already
    hold *there*, and simultaneously sell base asset you already hold on the
    *other* exchange. Every trade drifts both balances (base accumulates on the
    buy side, quote accumulates on the sell side) until someone transfers funds
    back to rebalance. This tracks that drift so the bot only takes trades the
    pre-positioned inventory can actually fund, and flags when a rebalance is due.
    """

    balances: dict[str, dict[str, float]]
    targets: dict[str, dict[str, float]]

    @classmethod
    def from_allocation(cls, allocation: dict[str, dict[str, float]]) -> "ExchangeBalances":
        snapshot = {eid: dict(currencies) for eid, currencies in allocation.items()}
        return cls(balances={eid: dict(c) for eid, c in snapshot.items()}, targets=snapshot)

    def available(self, exchange_id: str, currency: str) -> float:
        return self.balances.get(exchange_id, {}).get(currency, 0.0)

    def max_cross_exchange_quote_size(
        self, buy_exchange: str, sell_exchange: str, symbol: str, sell_price_estimate: float
    ) -> float:
        """Caps a candidate trade size (in quote currency) by what's actually
        pre-positioned: quote currency to buy with on `buy_exchange`, and base
        asset to sell on `sell_exchange` (converted to quote at the current
        price so it's comparable)."""
        base, quote = symbol.split("/")
        from_buy_side = self.available(buy_exchange, quote)
        from_sell_side = self.available(sell_exchange, base) * sell_price_estimate
        return max(0.0, min(from_buy_side, from_sell_side))

    def settle_cross_exchange_trade(
        self,
        buy_exchange: str,
        sell_exchange: str,
        symbol: str,
        quote_spent: float,
        base_bought: float,
        quote_received: float,
    ) -> None:
        base, quote = symbol.split("/")
        self.balances[buy_exchange][quote] = self.balances[buy_exchange].get(quote, 0.0) - quote_spent
        self.balances[buy_exchange][base] = self.balances[buy_exchange].get(base, 0.0) + base_bought
        self.balances[sell_exchange][base] = self.balances[sell_exchange].get(base, 0.0) - base_bought
        self.balances[sell_exchange][quote] = self.balances[sell_exchange].get(quote, 0.0) + quote_received

    def skew_warnings(self, warning_pct: float) -> list[str]:
        """Returns one message per currency/exchange whose balance has drifted
        below `warning_pct` of its initial target, signaling a manual transfer
        is due to keep funding future trades on that leg."""
        warnings = []
        for exchange_id, currencies in self.targets.items():
            for currency, target in currencies.items():
                if target <= 0:
                    continue
                current = self.available(exchange_id, currency)
                if current < target * warning_pct:
                    warnings.append(
                        f"{exchange_id}: saldo de {currency} caiu para {current:.6f} "
                        f"({current / target * 100:.1f}% do alvo inicial de {target}). "
                        "Considere transferir fundos para rebalancear."
                    )
        return warnings
