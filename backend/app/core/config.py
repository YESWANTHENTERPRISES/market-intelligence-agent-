import os
from typing import Optional, Dict
from pydantic_settings import BaseSettings, SettingsConfigDict

_ENV_PATH = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "../../.env")
)

class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=_ENV_PATH,
        env_file_encoding="utf-8",
        extra="ignore"
    )

    APP_NAME: str = "AI Market Intelligence API"
    HOST: str = "0.0.0.0"
    PORT: int = 8000
    DEBUG: bool = False  # Used for uvicorn reload flag
    ALLOW_CLIENT_PRICE_OVERRIDE: bool = False  # Default False: client/TradingView prices cannot silently override live spot feeds

    FINNHUB_API_KEY: str = ""
    FRED_API_KEY: str = ""
    GEMINI_API_KEY: str = ""

    CACHE_TTL_PRICE: int = 3
    CACHE_TTL_5M: int = 60
    CACHE_TTL_15M_30M: int = 120
    CACHE_TTL_1H_4H: int = 300
    CACHE_TTL_DOM: int = 30
    CACHE_TTL_NEWS: int = 300
    CACHE_TTL_MACRO: int = 14400

    # MetaTrader 5 (MT5) DOM Settings
    MT5_ENABLED: bool = False
    MT5_PATH: Optional[str] = None
    MT5_LOGIN: Optional[int] = None
    MT5_PASSWORD: Optional[str] = None
    MT5_SERVER: Optional[str] = None
    MT5_TIMEOUT: int = 5000
    MT5_PORTABLE: bool = False
    MT5_SYMBOL_MAP: Dict[str, str] = {
        "XAUUSD": "XAUUSD",
        "EURUSD": "EURUSD",
        "GBPUSD": "GBPUSD",
        "USDJPY": "USDJPY",
        "BTCUSD": "BTCUSD"
    }

    # Spotware cTrader Open API DOM Settings
    CTRADER_ENABLED: bool = False
    CTRADER_CLIENT_ID: Optional[str] = None
    CTRADER_CLIENT_SECRET: Optional[str] = None
    CTRADER_ACCESS_TOKEN: Optional[str] = None
    CTRADER_ACCOUNT_ID: Optional[int] = None
    CTRADER_HOST: str = "live.ctraderapi.com"
    CTRADER_PORT: int = 5035
    CTRADER_SYMBOL_MAP: Dict[str, str] = {
        "XAUUSD": "XAUUSD",
        "EURUSD": "EURUSD",
        "GBPUSD": "GBPUSD",
        "USDJPY": "USDJPY",
        "BTCUSD": "BTCUSD"
    }

settings = Settings()

