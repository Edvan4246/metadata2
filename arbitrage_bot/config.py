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


@dataclass
class LoggingConfig:
    level: str
    trades_log_path: str
    opportunities_log_path: str


@dataclass
class Settings:
    exchange_id: str
    base_currency: str
    triangular: TriangularConfig
    cross_exchange: CrossExchangeConfig
    risk: RiskConfig
    interval_seconds: int
    logging: LoggingConfig

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
        )
