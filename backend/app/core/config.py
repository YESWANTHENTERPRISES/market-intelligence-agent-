import os
from pydantic_settings import BaseSettings, SettingsConfigDict
from dotenv import load_dotenv

# Explicitly load .env from backend folder or root folder
backend_env = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../.env"))
root_env = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../.env"))

if os.path.exists(backend_env):
    load_dotenv(backend_env, override=True)
elif os.path.exists(root_env):
    load_dotenv(root_env, override=True)

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    APP_NAME: str = "AI Market Intelligence API"
    HOST: str = "0.0.0.0"
    PORT: int = 8000
    
    # API Keys
    FINNHUB_API_KEY: str = os.getenv("FINNHUB_API_KEY", "")
    FRED_API_KEY: str = os.getenv("FRED_API_KEY", "")
    GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")
    
    # Cache TTL (seconds)
    CACHE_TTL_PRICE: int = 3
    CACHE_TTL_5M: int = 60
    CACHE_TTL_15M_30M: int = 120
    CACHE_TTL_1H_4H: int = 300
    CACHE_TTL_DOM: int = 30
    CACHE_TTL_NEWS: int = 300
    CACHE_TTL_MACRO: int = 14400  # 4 hours

settings = Settings()
