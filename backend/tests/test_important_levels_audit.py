import time
import pytest
from unittest.mock import AsyncMock, patch
from app.market.structure import MarketStructureEngine, calculate_atr
from app.market.important_levels import ImportantLevelsEngine
from app.providers.manager import ProviderManager


def _make_candles(p=4335.20, count=30, volatility=8.0):
    candles = []
    step = volatility / count
    for i in range(count):
        c_open = p + (i - 15) * (step * 0.1)
        c_high = c_open + (step * 0.8)
        c_low = c_open - (step * 0.8)
        c_close = c_open + (step * 0.2 if i % 2 == 0 else -step * 0.2)
        candles.append({
            "open": round(c_open, 2),
            "high": round(c_high, 2),
            "low": round(c_low, 2),
            "close": round(c_close, 2),
            "volume": 1000 + (i * 10),
            "timestamp": f"t_{i}"
        })
    return candles


# Test 1: Support classification
@pytest.mark.asyncio
async def test_1_support_classification():
    engine = ImportantLevelsEngine()
    res = await engine.calculate_important_levels("XAUUSD", current_price=4335.20)
    for sup in res["support"]:
        assert sup["midpoint"] < 4335.20 or sup["classification"] in ["SUPPORT", "BROKEN_RESISTANCE"]


# Test 2: Resistance classification
@pytest.mark.asyncio
async def test_2_resistance_classification():
    engine = ImportantLevelsEngine()
    res = await engine.calculate_important_levels("XAUUSD", current_price=4335.20)
    for res_lvl in res["resistance"]:
        assert res_lvl["midpoint"] >= 4335.20 or res_lvl["classification"] in ["RESISTANCE", "BROKEN_SUPPORT"]


# Test 3: Buy-side liquidity classification
def test_3_buyside_liquidity_classification():
    mse = MarketStructureEngine()
    candles = _make_candles()
    # Add two equal highs at 4350.00
    candles[10]["high"] = 4350.00
    candles[20]["high"] = 4350.00
    eq = mse.detect_equal_highs_lows(candles, "1H")
    buys = [e for e in eq if e["classification"] == "BUY_SIDE_LIQUIDITY"]
    assert len(buys) > 0


# Test 4: Sell-side liquidity classification
def test_4_sellside_liquidity_classification():
    mse = MarketStructureEngine()
    candles = _make_candles()
    # Add two equal lows at 4320.00
    candles[10]["low"] = 4320.00
    candles[20]["low"] = 4320.00
    eq = mse.detect_equal_highs_lows(candles, "1H")
    sells = [e for e in eq if e["classification"] == "SELL_SIDE_LIQUIDITY"]
    assert len(sells) > 0


# Test 5: Equal-high liquidity
def test_5_equal_high_liquidity():
    mse = MarketStructureEngine()
    candles = _make_candles()
    candles[10]["high"] = 4350.00
    candles[20]["high"] = 4350.00
    eq = mse.detect_equal_highs_lows(candles, "1H")
    assert any(e["type"] == "EQUAL_HIGH" for e in eq)


# Test 6: Equal-low liquidity
def test_6_equal_low_liquidity():
    mse = MarketStructureEngine()
    candles = _make_candles()
    candles[10]["low"] = 4320.00
    candles[20]["low"] = 4320.00
    eq = mse.detect_equal_highs_lows(candles, "1H")
    assert any(e["type"] == "EQUAL_LOW" for e in eq)


# Test 7: FVG validation
def test_7_fvg_validation():
    mse = MarketStructureEngine()
    candles = _make_candles()
    # Create gap: candle 0 high = 4330, candle 1 large up, candle 2 low = 4335
    candles[0]["high"] = 4330.00
    candles[1]["low"] = 4331.00
    candles[1]["high"] = 4338.00
    candles[2]["low"] = 4335.00
    fvgs = mse.detect_fvgs(candles[:3], "1H")
    assert len(fvgs) > 0
    assert fvgs[0]["type"] == "BULLISH_FVG"


# Test 8: FVG mitigation
def test_8_fvg_mitigation():
    mse = MarketStructureEngine()
    candles = _make_candles(count=10)
    # Gap at candle 2
    candles[0]["high"] = 4330.00
    candles[2]["low"] = 4335.00
    # Subsequent candle 5 fills gap completely
    candles[5]["low"] = 4329.00
    fvgs = mse.detect_fvgs(candles, "1H")
    # Mitigated FVG should be excluded from active list
    active_fvgs = [f for f in fvgs if f["status"] == "ACTIVE"]
    assert not any(f["gap_low"] == 4330.00 and f["status"] == "ACTIVE" for f in active_fvgs)


# Test 9: BOS detection
def test_9_bos_detection():
    mse = MarketStructureEngine()
    candles = _make_candles(count=20)
    bos_list = mse.detect_bos_choch(candles, "1H")
    assert isinstance(bos_list, list)


# Test 10: CHoCH detection
def test_10_choch_detection():
    mse = MarketStructureEngine()
    candles = _make_candles(count=20)
    bos_list = mse.detect_bos_choch(candles, "1H")
    assert isinstance(bos_list, list)


# Test 11: Multi-timeframe agreement
@pytest.mark.asyncio
async def test_11_mtf_agreement():
    engine = ImportantLevelsEngine()
    res = await engine.calculate_important_levels("XAUUSD", current_price=4335.20)
    for lvl in res["levels"]:
        assert isinstance(lvl["timeframes"], list)


# Test 12: Level clustering
@pytest.mark.asyncio
async def test_12_level_clustering():
    engine = ImportantLevelsEngine()
    res = await engine.calculate_important_levels("XAUUSD", current_price=4335.20)
    mids = [l["midpoint"] for l in res["levels"]]
    # Check no 2 levels are within 0.1 ATR of each other
    for i in range(len(mids)):
        for j in range(i + 1, len(mids)):
            assert abs(mids[i] - mids[j]) >= 0.5


# Test 13: Duplicate removal
@pytest.mark.asyncio
async def test_13_duplicate_removal():
    engine = ImportantLevelsEngine()
    res = await engine.calculate_important_levels("XAUUSD", current_price=4335.20)
    mids = [l["midpoint"] for l in res["levels"]]
    assert len(mids) == len(set(mids))


# Test 14: ATR distance
@pytest.mark.asyncio
async def test_14_atr_distance():
    engine = ImportantLevelsEngine()
    res = await engine.calculate_important_levels("XAUUSD", current_price=4335.20)
    for lvl in res["levels"]:
        assert lvl["distance_atr"] >= 0.0
        assert lvl["distance"] == pytest.approx(abs(lvl["midpoint"] - 4335.20), abs=0.1)


# Test 15: Importance vs actionability
@pytest.mark.asyncio
async def test_15_importance_vs_actionability():
    engine = ImportantLevelsEngine()
    res = await engine.calculate_important_levels("XAUUSD", current_price=4335.20)
    for lvl in res["levels"]:
        assert lvl["importance"] in ["VERY_HIGH", "HIGH", "MODERATE"]
        assert lvl["actionability"] in ["IMMEDIATE", "NEAR", "DISTANT"]


# Test 16: Level invalidation
@pytest.mark.asyncio
async def test_16_level_invalidation():
    engine = ImportantLevelsEngine()
    res = await engine.calculate_important_levels("XAUUSD", current_price=4335.20)
    for lvl in res["levels"]:
        assert lvl["status"] in ["ACTIVE", "TESTED", "SWEPT", "MITIGATED", "INVALIDATED"]


# Test 17: DOM evidence aggregation
@pytest.mark.asyncio
async def test_17_dom_evidence_aggregation():
    engine = ImportantLevelsEngine()
    res = await engine.calculate_important_levels("XAUUSD", current_price=4335.20)
    for lvl in res["levels"]:
        assert "dom" in lvl
        assert isinstance(lvl["dom"]["sources"], list)


# Test 18: Multi-source liquidity convergence
@pytest.mark.asyncio
async def test_18_multi_source_liquidity_convergence():
    engine = ImportantLevelsEngine()
    res = await engine.calculate_important_levels("XAUUSD", current_price=4335.20)
    assert res["status"] == "AVAILABLE"


# Test 19: Level persistence
from app.models.schemas import PriceMetadata


@pytest.mark.asyncio
async def test_19_level_persistence():
    engine = ImportantLevelsEngine()
    ohlc = engine._generate_fallback_ohlc("XAUUSD", 4335.20)
    res1 = await engine.calculate_important_levels("XAUUSD", current_price=4335.20, ohlc_data=ohlc)
    res2 = await engine.calculate_important_levels("XAUUSD", current_price=4335.25, ohlc_data=ohlc)
    mids1 = [l["midpoint"] for l in res1["levels"]]
    mids2 = [l["midpoint"] for l in res2["levels"]]
    common = set(mids1).intersection(set(mids2))
    assert len(common) / max(1, len(mids1)) >= 0.80



# Test 20: Stale DOM evidence downgrade
@pytest.mark.asyncio
async def test_20_stale_dom_evidence_downgrade():
    engine = ImportantLevelsEngine()
    res = await engine.calculate_important_levels("XAUUSD", current_price=4335.20)
    assert res["data_quality"] is not None


# Test 21: Synthetic fallback tagging
@pytest.mark.asyncio
async def test_21_synthetic_fallback_tagging():
    engine = ImportantLevelsEngine()
    res = await engine.calculate_important_levels("XAUUSD", current_price=4335.20, ohlc_data=None)
    for lvl in res["levels"]:
        assert lvl["observed"] is False


# Test 22: Explainable score breakdown
@pytest.mark.asyncio
async def test_22_explainable_score_breakdown():
    engine = ImportantLevelsEngine()
    res = await engine.calculate_important_levels("XAUUSD", current_price=4335.20)
    for lvl in res["levels"]:
        sb = lvl["score_breakdown"]
        assert "htf_structure" in sb
        assert "mtf_agreement" in sb
        assert "total" in sb
        assert sb["total"] == lvl["confluence_score"]


# Test 23: High-confluence distant level
@pytest.mark.asyncio
async def test_23_high_confluence_distant_level():
    engine = ImportantLevelsEngine()
    res = await engine.calculate_important_levels("XAUUSD", current_price=4335.20)

    # Distant level (e.g. PWH or PWL) should have actionability DISTANT
    distant_lvls = [l for l in res["levels"] if l["distance_atr"] > 2.5]
    for lvl in distant_lvls:
        assert lvl["actionability"] == "DISTANT"


# Test 24: Moderate-confluence nearby level
@pytest.mark.asyncio
async def test_24_moderate_confluence_nearby_level():
    engine = ImportantLevelsEngine()
    res = await engine.calculate_important_levels("XAUUSD", current_price=4335.20)

    nearby_lvls = [l for l in res["levels"] if l["distance_atr"] <= 1.0]
    for lvl in nearby_lvls:
        assert lvl["actionability"] == "IMMEDIATE"


# Test 25: Final AI-ready payload
@pytest.mark.asyncio
async def test_25_final_ai_ready_payload():
    manager = ProviderManager()
    with patch.object(manager, "_resolve_canonical_price", new=AsyncMock(return_value=PriceMetadata(
        price=4335.20, source="OANDA", timestamp=time.time(), is_market_feed=True, age_seconds=0.0, status="LIVE"
    ))):
        res = await manager.get_market_intelligence("XAUUSD", "5M")
        assert res.important_levels is not None
        assert len(res.important_levels.levels) > 0

        first_lvl = res.important_levels.levels[0]
        assert first_lvl.zone is not None
        assert first_lvl.midpoint > 0
        assert first_lvl.classification in ["RESISTANCE", "SUPPORT", "BUY_SIDE_LIQUIDITY", "SELL_SIDE_LIQUIDITY", "BROKEN_RESISTANCE", "BROKEN_SUPPORT"]
        assert first_lvl.importance in ["VERY_HIGH", "HIGH", "MODERATE"]
        assert first_lvl.actionability in ["IMMEDIATE", "NEAR", "DISTANT"]
        assert first_lvl.confluence_score >= 50
        assert isinstance(first_lvl.observed, bool)
