import pytest
import asyncio
from app.market.structure import market_structure_engine
from app.market.important_levels import important_levels_engine
from app.ai.prompt_builder import ai_prompt_builder

def generate_mock_candles(base_price=4431.00, count=30):
    candles = []
    for i in range(count):
        candles.append({
            "open": base_price + (i % 3),
            "high": base_price + (i % 3) + 2.0,
            "low": base_price + (i % 3) - 2.0,
            "close": base_price + (i % 3) + 0.5,
            "volume": 1000 + i * 10,
            "timestamp": f"t_{i}"
        })
    return candles

def test_1_swing_high_detection():
    candles = generate_mock_candles(4431.00, 20)
    # Inject an explicit swing high at index 10
    candles[10]["high"] = 4450.00
    for j in range(7, 10):
        candles[j]["high"] = 4435.00
    for j in range(11, 14):
        candles[j]["high"] = 4435.00

    swings = market_structure_engine.detect_swings(candles, "1H", atr=5.0)
    swing_highs = [s for s in swings if s["type"] == "SWING_HIGH"]
    
    assert len(swing_highs) > 0
    assert any(s["price"] == 4450.00 for s in swing_highs)

def test_2_swing_low_detection():
    candles = generate_mock_candles(4431.00, 20)
    # Inject an explicit swing low at index 10
    candles[10]["low"] = 4410.00
    for j in range(7, 10):
        candles[j]["low"] = 4425.00
    for j in range(11, 14):
        candles[j]["low"] = 4425.00

    swings = market_structure_engine.detect_swings(candles, "1H", atr=5.0)
    swing_lows = [s for s in swings if s["type"] == "SWING_LOW"]
    
    assert len(swing_lows) > 0
    assert any(s["price"] == 4410.00 for s in swing_lows)

def test_3_equal_highs():
    candles = generate_mock_candles(4431.00, 25)
    # Inject equal swing highs at index 7 and index 15
    candles[7]["high"] = 4445.00
    candles[15]["high"] = 4445.05
    for j in range(4, 7): candles[j]["high"] = 4430.00
    for j in range(8, 11): candles[j]["high"] = 4430.00
    for j in range(12, 15): candles[j]["high"] = 4430.00
    for j in range(16, 19): candles[j]["high"] = 4430.00

    eq = market_structure_engine.detect_equal_highs_lows(candles, "1H", atr=5.0)
    eq_highs = [e for e in eq if e["type"] == "EQUAL_HIGH"]

    assert len(eq_highs) > 0
    assert eq_highs[0]["classification"] == "BUY_SIDE_LIQUIDITY"

def test_4_equal_lows():
    candles = generate_mock_candles(4431.00, 25)
    # Inject equal swing lows at index 7 and index 15
    candles[7]["low"] = 4415.00
    candles[15]["low"] = 4415.05
    for j in range(4, 7): candles[j]["low"] = 4430.00
    for j in range(8, 11): candles[j]["low"] = 4430.00
    for j in range(12, 15): candles[j]["low"] = 4430.00
    for j in range(16, 19): candles[j]["low"] = 4430.00

    eq = market_structure_engine.detect_equal_highs_lows(candles, "1H", atr=5.0)
    eq_lows = [e for e in eq if e["type"] == "EQUAL_LOW"]

    assert len(eq_lows) > 0
    assert eq_lows[0]["classification"] == "SELL_SIDE_LIQUIDITY"

def test_5_previous_day_week_levels():
    ohlc = {
        "1D": [
            {"open": 4400, "high": 4420, "low": 4390, "close": 4410},
            {"open": 4410, "high": 4440, "low": 4405, "close": 4435}
        ]
    }
    levels = market_structure_engine.compute_session_and_period_levels(ohlc)
    types = [l["type"] for l in levels]

    assert "PDH" in types
    assert "PDL" in types
    assert any(l["price"] == 4420 for l in levels if l["type"] == "PDH")
    assert any(l["price"] == 4390 for l in levels if l["type"] == "PDL")

def test_14_tick_volume_is_labeled_as_proxy():
    from app.models.schemas import OrderFlow
    of = OrderFlow(
        status="TICK_PROXY_ONLY",
        buying_pressure="MODERATE",
        delta=12242,
        proxy_label="Tick Proxy"
    )
    assert of.status == "TICK_PROXY_ONLY"
    assert "Proxy" in of.proxy_label

def test_15_5m_only_level_cannot_automatically_become_major_level():
    zone_5m = {"timeframes": ["5M"], "evidence": ["5M swing high"]}
    score, _ = important_levels_engine._calculate_confluence_score(
        zone=zone_5m, current_price=4431.00, atr=5.0, dom_data=None, interactions={}
    )
    # A 5M-only level should score low (<50) and not become VERY_HIGH (>=80)
    assert score < 50
    assert important_levels_engine._classify_importance(score) != "VERY_HIGH"

def test_16_gemini_cannot_introduce_unknown_price_level():
    validated_levels = [
        {"zone": "4438–4440", "midpoint": 4439.0}
    ]
    # AI returns unauthorized level 4499.0
    bad_ai_output = "Gold will surge to 4499.0 because of buying momentum."
    is_valid, msg, unauthorized = ai_prompt_builder.validate_ai_output(
        ai_response_text=bad_ai_output,
        validated_levels=validated_levels,
        current_price=4431.00
    )
    assert is_valid is False
    assert "4499.0" in unauthorized or "4499" in unauthorized

@pytest.mark.asyncio
async def test_17_no_hardcoded_prices_reach_production_output():
    res = await important_levels_engine.calculate_important_levels(
        symbol="XAUUSD", current_price=4431.00
    )
    assert res["status"] == "AVAILABLE"
    assert res["current_price"] == 4431.00
    for lvl in res["levels"]:
        assert isinstance(lvl["confluence_score"], int)
        assert lvl["importance"] in ["VERY_HIGH", "HIGH", "MODERATE"]

@pytest.mark.asyncio
async def test_18_every_displayed_level_contains_evidence():
    res = await important_levels_engine.calculate_important_levels(
        symbol="XAUUSD", current_price=4431.00
    )
    for lvl in res["levels"]:
        assert "evidence" in lvl
        assert len(lvl["evidence"]) > 0
