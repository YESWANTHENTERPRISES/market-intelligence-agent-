import os
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

settings = Settings()

