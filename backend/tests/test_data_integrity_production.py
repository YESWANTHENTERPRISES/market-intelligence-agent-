import pytest
import time
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch
from fastapi.testclient import TestClient
from app.main import app
from app.core.config import settings
from app.providers.manager import ProviderManager, is_market_open, _get_current_session
from app.providers.dom.models import SourceSnapshot, SourceStatus, PriceLevel
from app.providers.dom.engine import DOMEngine
from app.providers.dom.adapters import MT5DOMAdapter, CTraderDOMAdapter
from app.ai.prompt_builder import ai_prompt_builder
from app.models.schemas import SessionInfo

client = TestClient(app)


# 1. Market Hours & Weekend Awareness Test
def test_market_hours_and_weekend_awareness():
    # Saturday (2026-01-10 14:00 UTC) -> Market closed for Forex / Gold
    saturday_dt = datetime(2026, 1, 10, 14, 0, 0, tzinfo=timezone.utc)
    open_gold, reason_gold = is_market_open("XAUUSD", saturday_dt)
    assert open_gold is False
    assert "Weekend" in reason_gold

    session_gold = _get_current_session("XAUUSD", saturday_dt)
    assert session_gold.name == "MARKET_CLOSED"
    assert session_gold.volatility == "NONE"
    assert session_gold.relevance == "CLOSED"

    # Saturday for Crypto -> Market OPEN
    open_btc, reason_btc = is_market_open("BTCUSD", saturday_dt)
    assert open_btc is True
    assert "24/7" in reason_btc

    session_btc = _get_current_session("BTCUSD", saturday_dt)
    assert session_btc.name in ["London", "New York", "Asia", "Overlap/Close"]

    # Tuesday 14:00 UTC (New York) -> Market OPEN for Gold
    tuesday_dt = datetime(2026, 1, 13, 14, 0, 0, tzinfo=timezone.utc)
    open_tue, _ = is_market_open("XAUUSD", tuesday_dt)
    assert open_tue is True
    session_tue = _get_current_session("XAUUSD", tuesday_dt)
    assert session_tue.name == "New York"
    assert session_tue.volatility == "HIGH"


# 2. DOM Placeholder & Exclusion of Simulated Data Test
@pytest.mark.asyncio
async def test_dom_placeholder_adapters_and_exclusion():
    engine = DOMEngine()
    dom_intel = await engine.build_dom_intelligence("XAUUSD", 4431.00)

    # Without live feeds, DOM should report NO-SOURCE or 0 active sources
    assert "NO-SOURCE" in dom_intel.coverage
    for src in dom_intel.sources:
        assert src.included_in_aggregation is False
        assert src.status in ["UNAVAILABLE", "SIMULATED"]

    assert dom_intel.liquidity_status == "DATA NOT VERIFIED"
    assert dom_intel.retail_positioning == "UNAVAILABLE"
    assert dom_intel.futures_sell_wall == "UNAVAILABLE"
    assert dom_intel.basis == "UNAVAILABLE"
    assert dom_intel.data_quality == "UNAVAILABLE"


# 3. Honest Status on Failed / Missing Upstream Feeds Test
@pytest.mark.asyncio
async def test_honest_status_on_network_failure():
    mgr = ProviderManager()
    
    # Mock network client to fail on all requests
    with patch.object(mgr.client, "get", new=AsyncMock(side_effect=Exception("Network unreachable"))):
        intel = await mgr.get_market_intelligence("XAUUSD", "5M")

        # Must not silently claim LIVE on failed sources
        assert intel.correlations.dxy.status == "UNAVAILABLE"
        assert intel.correlations.us10y.status == "UNAVAILABLE"
        assert intel.fundamentals.status == "UNAVAILABLE"
        assert intel.data_status.dxy == "UNAVAILABLE"
        assert intel.data_status.us10y == "UNAVAILABLE"
        assert intel.data_status.fundamentals == "UNAVAILABLE"
        assert intel.data_status.cot == "UNAVAILABLE"
        assert intel.data_status.fed == "UNAVAILABLE"


# 4. Dynamic Candle Calculation Test
@pytest.mark.asyncio
async def test_dynamic_indicator_calculation_from_ohlc():
    mgr = ProviderManager()

    # 1. Bullish trending candles
    bullish_candles = [
        {"open": 4400.0 + i * 2, "high": 4405.0 + i * 2, "low": 4399.0 + i * 2, "close": 4404.0 + i * 2, "volume": 1000.0}
        for i in range(30)
    ]
    raw_bull = mgr._compute_raw_indicators_from_ohlc(bullish_candles, "5M")
    assert raw_bull["momentum"] > 50
    assert raw_bull["structure"] > 50
    assert raw_bull["orderflow"] > 50

    # 2. Bearish trending candles
    bearish_candles = [
        {"open": 4500.0 - i * 2, "high": 4501.0 - i * 2, "low": 4495.0 - i * 2, "close": 4496.0 - i * 2, "volume": 1000.0}
        for i in range(30)
    ]
    raw_bear = mgr._compute_raw_indicators_from_ohlc(bearish_candles, "5M")
    assert raw_bear["momentum"] < 50
    assert raw_bear["structure"] < 50
    assert raw_bear["orderflow"] < 50


# 5. Gemini AI Prompt Builder and Validator Test
def test_ai_prompt_builder_and_validation():
    levels_res = {
        "levels": [
            {"zone": "4430.00–4435.00", "midpoint": 4432.50, "classification": "SUPPORT", "importance": "HIGH", "confluence_score": 75, "evidence": ["4H swing low"]}
        ]
    }
    prompt = ai_prompt_builder.build_prompt_with_levels("XAUUSD", 4432.00, levels_res, "BUY")
    assert "4430.00–4435.00" in prompt
    assert "XAUUSD" in prompt
    assert "STRICT GEMINI RESTRICTIONS" in prompt

    # Output with legitimate validated level -> PASS
    valid_text = "SUPPORTING:\n- Price is holding strong above 4432.50 support\nCONFLICTING:\n- Minor resistance ahead"
    is_valid, _, _ = ai_prompt_builder.validate_ai_output(valid_text, levels_res["levels"], 4432.00)
    assert is_valid is True

    # Output with unauthorized invented level (e.g. 5980.00) -> REJECT
    hallucinated_text = "SUPPORTING:\n- Strong bounce expected from 5980.00\n"
    is_valid_bad, err, unauth = ai_prompt_builder.validate_ai_output(hallucinated_text, levels_res["levels"], 4432.00)
    assert is_valid_bad is False
    assert "5980.00" in err or "5980" in err


# 6. Config Key References Test
def test_all_config_keys_referenced():
    # Verify settings keys exist and can be accessed without errors
    assert hasattr(settings, "FINNHUB_API_KEY")
    assert hasattr(settings, "FRED_API_KEY")
    assert hasattr(settings, "GEMINI_API_KEY")
    assert hasattr(settings, "ALLOW_CLIENT_PRICE_OVERRIDE")
    assert hasattr(settings, "CACHE_TTL_PRICE")
    assert hasattr(settings, "CACHE_TTL_5M")
    assert hasattr(settings, "CACHE_TTL_MACRO")
    assert hasattr(settings, "CACHE_TTL_NEWS")


# 7. Endpoint Live API Response Test
def test_api_intelligence_schema_integrity():
    res = client.get("/api/intelligence?symbol=XAUUSD&timeframe=5M")
    assert res.status_code == 200
    data = res.json()

    assert data["symbol"] == "XAUUSD"
    assert "overall_bias" in data
    assert data["overall_bias"] in ["BUY", "SELL", "NEUTRAL"]
    assert "directional_pressure" in data
    assert "data_status" in data
    assert "session" in data
    assert "correlations" in data
    assert "fed_probabilities" in data
    assert "cot" in data
    assert data["cot"]["status"] == "UNAVAILABLE"
    assert data["fed_probabilities"]["status"] == "UNAVAILABLE"
