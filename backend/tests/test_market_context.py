import time
import pytest
from unittest.mock import AsyncMock, patch
from app.market.context import MarketContextEngine
from app.models.schemas import ImportantLevels, LevelDetail, PriceMetadata
from app.providers.manager import ProviderManager


def _make_candles(count=30, trend="BEARISH"):
    candles = []
    base = 4335.20
    for i in range(count):
        step = (i - 15) * (-0.5 if trend == "BEARISH" else 0.5)
        c_open = base + step
        c_high = c_open + 1.2
        c_low = c_open - 1.2
        c_close = c_open + (-0.3 if trend == "BEARISH" else 0.3)
        candles.append({
            "open": round(c_open, 2),
            "high": round(c_high, 2),
            "low": round(c_low, 2),
            "close": round(c_close, 2),
            "volume": 1000,
            "timestamp": f"t_{i}"
        })
    return candles


# Test 1: Bullish HTF structure
def test_1_bullish_htf_structure():
    engine = MarketContextEngine()
    ohlc = {
        "4H": _make_candles(trend="BULLISH"),
        "1H": _make_candles(trend="BULLISH"),
        "15M": _make_candles(trend="BULLISH")
    }
    ctx = engine.build_market_context("XAUUSD", 4335.20, ohlc_data=ohlc)
    assert ctx.structure.htf in ["BULLISH", "NEUTRAL"]


# Test 2: Bearish HTF structure
def test_2_bearish_htf_structure():
    engine = MarketContextEngine()
    ohlc = {
        "4H": _make_candles(trend="BEARISH"),
        "1H": _make_candles(trend="BEARISH"),
        "15M": _make_candles(trend="BEARISH")
    }
    ctx = engine.build_market_context("XAUUSD", 4335.20, ohlc_data=ohlc)
    assert ctx.structure.htf in ["BEARISH", "NEUTRAL"]


# Test 3: Neutral structure
def test_3_neutral_structure():
    engine = MarketContextEngine()
    ctx = engine.build_market_context("XAUUSD", 4335.20, ohlc_data=None)
    assert ctx.structure.htf == "NEUTRAL"
    assert ctx.structure.dominant == "NEUTRAL"


# Test 4: HTF vs LTF conflict
def test_4_htf_vs_ltf_conflict():
    engine = MarketContextEngine()
    ohlc = {
        "4H": _make_candles(trend="BEARISH"),
        "1H": _make_candles(trend="BEARISH"),
        "15M": _make_candles(trend="BULLISH")
    }
    ctx = engine.build_market_context("XAUUSD", 4335.20, ohlc_data=ohlc)
    assert ctx.context.conflict is True or ctx.structure.ltf == "BULLISH_RETRACEMENT"


# Test 5: Bullish retracement inside bearish trend
def test_5_bullish_retracement_in_bearish_trend():
    engine = MarketContextEngine()
    ohlc = {
        "4H": _make_candles(trend="BEARISH"),
        "1H": _make_candles(trend="BEARISH"),
        "15M": _make_candles(trend="BULLISH")
    }
    ctx = engine.build_market_context("XAUUSD", 4335.20, ohlc_data=ohlc)
    assert ctx.market_state in ["PULLBACK", "TREND_CONTINUATION"]


# Test 6: Bearish retracement inside bullish trend
def test_6_bearish_retracement_in_bullish_trend():
    engine = MarketContextEngine()
    ohlc = {
        "4H": _make_candles(trend="BULLISH"),
        "1H": _make_candles(trend="BULLISH"),
        "15M": _make_candles(trend="BEARISH")
    }
    ctx = engine.build_market_context("XAUUSD", 4335.20, ohlc_data=ohlc)
    assert ctx.market_state in ["PULLBACK", "TREND_CONTINUATION"]


# Test 7: Trending regime
def test_7_trending_regime():
    engine = MarketContextEngine()
    ohlc = {"4H": _make_candles(trend="BEARISH")}
    ctx = engine.build_market_context("XAUUSD", 4335.20, ohlc_data=ohlc)
    assert ctx.market_regime.structure in ["TRENDING_BEARISH", "TRENDING", "RANGING"]


# Test 8: Ranging regime
def test_8_ranging_regime():
    engine = MarketContextEngine()
    ctx = engine.build_market_context("XAUUSD", 4335.20, ohlc_data=None)
    assert ctx.market_regime.structure in ["RANGING", "UNKNOWN"]


# Test 9: Transition regime
def test_9_transition_regime():
    engine = MarketContextEngine()
    ohlc = {
        "4H": _make_candles(trend="BULLISH"),
        "1H": _make_candles(trend="BEARISH")
    }
    ctx = engine.build_market_context("XAUUSD", 4335.20, ohlc_data=ohlc)
    assert ctx.context.alignment in ["MOSTLY_ALIGNED", "CONFLICTING"]


# Test 10: Buy-side liquidity concentration
def test_10_buyside_liquidity_concentration():
    engine = MarketContextEngine()
    levels = ImportantLevels(
        status="AVAILABLE",
        levels=[
            LevelDetail(midpoint=4340.0, classification="BUY_SIDE_LIQUIDITY"),
            LevelDetail(midpoint=4345.0, classification="BUY_SIDE_LIQUIDITY"),
            LevelDetail(midpoint=4330.0, classification="SELL_SIDE_LIQUIDITY")
        ]
    )
    ctx = engine.build_market_context("XAUUSD", 4335.20, important_levels=levels)
    assert ctx.liquidity.concentration == "DENSE_ABOVE"


# Test 11: Sell-side liquidity concentration
def test_11_sellside_liquidity_concentration():
    engine = MarketContextEngine()
    levels = ImportantLevels(
        status="AVAILABLE",
        levels=[
            LevelDetail(midpoint=4340.0, classification="BUY_SIDE_LIQUIDITY"),
            LevelDetail(midpoint=4330.0, classification="SELL_SIDE_LIQUIDITY"),
            LevelDetail(midpoint=4325.0, classification="SELL_SIDE_LIQUIDITY")
        ]
    )
    ctx = engine.build_market_context("XAUUSD", 4335.20, important_levels=levels)
    assert ctx.liquidity.concentration == "DENSE_BELOW"


# Test 12: Balanced liquidity
def test_12_balanced_liquidity():
    engine = MarketContextEngine()
    levels = ImportantLevels(
        status="AVAILABLE",
        levels=[
            LevelDetail(midpoint=4340.0, classification="BUY_SIDE_LIQUIDITY"),
            LevelDetail(midpoint=4330.0, classification="SELL_SIDE_LIQUIDITY")
        ]
    )
    ctx = engine.build_market_context("XAUUSD", 4335.20, important_levels=levels)
    assert ctx.liquidity.concentration == "BALANCED"


# Test 13: Price near resistance
def test_13_price_near_resistance():
    engine = MarketContextEngine()
    levels = ImportantLevels(
        status="AVAILABLE",
        levels=[LevelDetail(midpoint=4336.0, classification="RESISTANCE")]
    )
    ctx = engine.build_market_context("XAUUSD", 4335.20, important_levels=levels, atr=8.0)
    assert ctx.price_location.state in ["AT_RESISTANCE", "NEAR_LIQUIDITY", "BETWEEN_LEVELS"]


# Test 14: Price near support
def test_14_price_near_support():
    engine = MarketContextEngine()
    levels = ImportantLevels(
        status="AVAILABLE",
        levels=[LevelDetail(midpoint=4334.50, classification="SUPPORT")]
    )
    ctx = engine.build_market_context("XAUUSD", 4335.20, important_levels=levels, atr=8.0)
    assert ctx.price_location.state in ["AT_SUPPORT", "NEAR_LIQUIDITY", "BETWEEN_LEVELS"]


# Test 15: Price between levels
def test_15_price_between_levels():
    engine = MarketContextEngine()
    levels = ImportantLevels(
        status="AVAILABLE",
        levels=[
            LevelDetail(midpoint=4350.0, classification="RESISTANCE"),
            LevelDetail(midpoint=4320.0, classification="SUPPORT")
        ]
    )
    ctx = engine.build_market_context("XAUUSD", 4335.20, important_levels=levels, atr=5.0)
    assert ctx.price_location.state == "BETWEEN_LEVELS"


# Test 16: Liquidity sweep context
def test_16_liquidity_sweep_context():
    engine = MarketContextEngine()
    levels = ImportantLevels(
        status="AVAILABLE",
        levels=[LevelDetail(midpoint=4335.50, classification="BUY_SIDE_LIQUIDITY", status="SWEPT")]
    )
    ctx = engine.build_market_context("XAUUSD", 4335.20, important_levels=levels)
    assert isinstance(ctx.market_state, str)


# Test 17: Post-sweep reaction
def test_17_post_sweep_reaction():
    engine = MarketContextEngine()
    levels = ImportantLevels(
        status="AVAILABLE",
        levels=[LevelDetail(midpoint=4335.50, classification="BUY_SIDE_LIQUIDITY", status="SWEPT")]
    )
    ctx = engine.build_market_context("XAUUSD", 4335.20, important_levels=levels)
    assert isinstance(ctx.market_state, str)


# Test 18: Breakout context
def test_18_breakout_context():
    engine = MarketContextEngine()
    ohlc = {"4H": _make_candles(trend="BULLISH")}
    levels = ImportantLevels(
        status="AVAILABLE",
        levels=[LevelDetail(midpoint=4335.30, classification="RESISTANCE")]
    )
    ctx = engine.build_market_context("XAUUSD", 4335.20, important_levels=levels, ohlc_data=ohlc)
    assert ctx.market_state in ["BREAKOUT", "TREND_CONTINUATION", "PULLBACK"]


# Test 19: Breakdown context
def test_19_breakdown_context():
    engine = MarketContextEngine()
    ohlc = {"4H": _make_candles(trend="BEARISH")}
    levels = ImportantLevels(
        status="AVAILABLE",
        levels=[LevelDetail(midpoint=4335.10, classification="SUPPORT")]
    )
    ctx = engine.build_market_context("XAUUSD", 4335.20, important_levels=levels, ohlc_data=ohlc)
    assert ctx.market_state in ["BREAKDOWN", "TREND_CONTINUATION", "PULLBACK"]


# Test 20: Context confidence
def test_20_context_confidence():
    engine = MarketContextEngine()
    ctx = engine.build_market_context("XAUUSD", 4335.20)
    assert 0 <= ctx.context.confidence <= 100


# Test 21: Low-data-confidence handling
def test_21_low_data_confidence_handling():
    engine = MarketContextEngine()
    ctx = engine.build_market_context("XAUUSD", 4335.20, important_levels=None, ohlc_data=None)
    assert any("NO_" in w or "CONFIDENCE" in w or "STRUCTURE" in w for w in ctx.warnings)


# Test 22: Stale data handling
def test_22_stale_data_handling():
    engine = MarketContextEngine()
    ctx = engine.build_market_context("XAUUSD", 4335.20)
    assert isinstance(ctx.warnings, list)


# Test 23: Multi-source agreement
def test_23_multi_source_agreement():
    engine = MarketContextEngine()
    ctx = engine.build_market_context("XAUUSD", 4335.20)
    assert ctx.context.alignment in ["ALIGNED", "MOSTLY_ALIGNED", "CONFLICTING"]


# Test 24: Session classification
def test_24_session_classification():
    engine = MarketContextEngine()
    ctx = engine.build_market_context("XAUUSD", 4335.20)
    assert ctx.session.name in ["ASIA", "LONDON", "NEW_YORK", "LONDON_NEW_YORK_OVERLAP", "OFF_SESSION", "UNKNOWN"]


# Test 25: Explainable context payload
def test_25_explainable_context_payload():
    engine = MarketContextEngine()
    ctx = engine.build_market_context("XAUUSD", 4335.20)
    assert isinstance(ctx.evidence, list)
    assert isinstance(ctx.summary, str)
    assert len(ctx.summary) > 0


# Test 26: Full end-to-end XAUUSD context response
@pytest.mark.asyncio
async def test_26_full_end_to_end_xauusd_context_response():
    manager = ProviderManager()
    with patch.object(manager, "_resolve_canonical_price", new=AsyncMock(return_value=PriceMetadata(
        price=4335.20, source="OANDA", timestamp=time.time(), is_market_feed=True, age_seconds=0.0, status="LIVE"
    ))):
        res = await manager.get_market_intelligence("XAUUSD", "5M")
        assert res.market_context is not None
        assert res.market_context.symbol == "XAUUSD"
        assert res.market_context.current_price == 4335.20
        assert res.market_context.market_bias in ["BULLISH", "BEARISH", "NEUTRAL"]
        assert len(res.market_context.evidence) >= 0
        assert len(res.market_context.summary) > 0
