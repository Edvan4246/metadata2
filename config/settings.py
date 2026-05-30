from pydantic_settings import BaseSettings
from pydantic import Field
from typing import List


class Settings(BaseSettings):
    # MT5 credentials
    mt5_login: int = Field(default=0, alias="MT5_LOGIN")
    mt5_password: str = Field(default="", alias="MT5_PASSWORD")
    mt5_server: str = Field(default="MetaQuotes-Demo", alias="MT5_SERVER")

    # Trading
    symbols: List[str] = Field(default=["EURUSD", "GBPUSD", "USDJPY"], alias="SYMBOLS")
    magic_number: int = Field(default=20240101, alias="MAGIC_NUMBER")
    lot_size: float = Field(default=0.01, alias="LOT_SIZE")

    # Risk
    max_risk_per_trade: float = Field(default=0.02, alias="MAX_RISK_PER_TRADE")
    max_daily_drawdown: float = Field(default=0.06, alias="MAX_DAILY_DRAWDOWN")
    max_open_positions: int = Field(default=4, alias="MAX_OPEN_POSITIONS")
    max_spread_points: int = Field(default=30, alias="MAX_SPREAD_POINTS")

    # API
    api_host: str = Field(default="0.0.0.0", alias="API_HOST")
    api_port: int = Field(default=8000, alias="API_PORT")
    api_secret_key: str = Field(default="changeme", alias="API_SECRET_KEY")

    # Logging
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")

    model_config = {"env_file": ".env", "populate_by_name": True}

    def symbols_list(self) -> List[str]:
        if isinstance(self.symbols, str):
            return [s.strip() for s in self.symbols.split(",")]
        return self.symbols


settings = Settings()
