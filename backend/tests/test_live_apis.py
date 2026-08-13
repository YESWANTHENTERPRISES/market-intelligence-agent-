import pytest
import asyncio
import httpx
from app.core.config import settings
from app.providers.manager import provider_manager

@pytest.mark.asyncio
async def test_finnhub_live_quote():
    if not settings.FINNHUB_API_KEY or "your_" in settings.FINNHUB_API_KEY:
        pytest.skip("Finnhub API key not set")
    
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            res = await client.get(
                f"https://finnhub.io/api/v1/quote?symbol=AAPL&token={settings.FINNHUB_API_KEY}"
            )
            assert res.status_code == 200
            data = res.json()
            assert "c" in data
    except (httpx.ReadTimeout, httpx.ConnectTimeout):
        pytest.skip("Finnhub API network connection timed out")

@pytest.mark.asyncio
async def test_fred_macro_data():
    if not settings.FRED_API_KEY or "your_" in settings.FRED_API_KEY:
        pytest.skip("FRED API key not set")

    async with httpx.AsyncClient() as client:
        res = await client.get(
            f"https://api.stlouisfed.org/fred/series/observations?series_id=DGS10&api_key={settings.FRED_API_KEY}&file_type=json"
        )
        assert res.status_code == 200
        data = res.json()
        assert "observations" in data

@pytest.mark.asyncio
async def test_provider_manager_all_symbols():
    symbols = ["XAUUSD", "EURUSD", "GBPUSD", "USDJPY", "BTCUSD"]
    for sym in symbols:
        intel = await provider_manager.get_market_intelligence(sym, "5M")
        assert intel.symbol == sym
        assert intel.current_price > 0
        assert intel.overall_bias in ["BUY", "SELL", "NEUTRAL"]
        assert intel.directional_pressure is not None
        assert intel.fundamentals is not None
        assert intel.data_status is not None
