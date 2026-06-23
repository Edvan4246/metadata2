from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass
class RiskConfig:
    initial_capital: float
    max_trade_pct: float
    min_profit_pct: float
    max_daily_loss_pct: float
    taker_fee_pct: float


@dataclass
class TriangularConfig:
    enabled: bool
    alt_currencies: list[str]


@dataclass
class CrossExchangeConfig:
    enabled: bool
    exchanges: list[str]
    symbols: list[str]
    # Capital pre-posicionado por exchange ({exchange_id: {currency: amount}}).
    # Sem isso, trades cross-exchange ficam sem inventario para validar (ver
    # arbitrage_bot/balances.py) e nunca sao executados.
    allocation: dict[str, dict[str, float]] = field(default_factory=dict)
    # Avisa quando o saldo de uma moeda numa exchange cai abaixo desta fracao
    # do saldo inicial alocado -- sinal de que e hora de rebalancear.
    rebalance_warning_pct: float = 0.5


@dataclass
class LoggingConfig:
    level: str
    trades_log_path: str
    opportunities_log_path: str


@dataclass
class LiveConfig:
    # Apenas um dos tres portoes exigidos para enviar ordens reais (ver
    # arbitrage_bot/live_executor.is_live_trading_enabled). Os outros dois sao
    # a flag --live na linha de comando e a variavel de ambiente
    # ARBITRAGE_BOT_LIVE_CONFIRM. Os tres precisam estar ativos ao mesmo tempo.
    enabled: bool = False
    order_timeout_seconds: float = 10.0


@dataclass
class Settings:
    exchange_id: str
    base_currency: str
    triangular: TriangularConfig
    cross_exchange: CrossExchangeConfig
    risk: RiskConfig
    interval_seconds: int
    logging: LoggingConfig
    live: LiveConfig = field(default_factory=LiveConfig)

    @staticmethod
    def load(path: str | Path) -> "Settings":
        raw = yaml.safe_load(Path(path).read_text())
        return Settings(
            exchange_id=raw["exchange"]["id"],
            base_currency=raw["base_currency"],
            triangular=TriangularConfig(**raw["triangular"]),
            cross_exchange=CrossExchangeConfig(**raw["cross_exchange"]),
            risk=RiskConfig(**raw["risk"]),
            interval_seconds=raw["loop"]["interval_seconds"],
            logging=LoggingConfig(**raw["logging"]),
            live=LiveConfig(**raw.get("live", {})),
        )
