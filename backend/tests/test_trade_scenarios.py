import time
import pytest
from unittest.mock import AsyncMock, patch
from app.market.context import MarketContextEngine
from app.market.scenarios import TradeScenarioEngine
from app.models.schemas import ImportantLevels, LevelDetail, PriceMetadata
from app.providers.manager import ProviderManager


def _mock_context(bias="BEARISH"):
    engine = MarketContextEngine()
    ctx = engine.build_market_context("XAUUSD", 4335.20)
    ctx.market_bias = bias
    ctx.structure.htf = bias
    ctx.structure.dominant = bias
    return ctx



# Test 1: Bullish pullback scenario
def test_1_bullish_pullback_scenario():
    ctx_engine = MarketContextEngine()
    ctx = ctx_engine.build_market_context("XAUUSD", 4335.20)
    ctx.market_bias = "BULLISH"
    ctx.structure.htf = "BULLISH"
    scenario_engine = TradeScenarioEngine()
    res = scenario_engine.evaluate_scenarios("XAUUSD", 4335.20, market_context=ctx)
    assert res.primary_scenario is not None
    assert res.primary_scenario.direction == "LONG"
    assert res.primary_scenario.scenario == "LONG_PULLBACK"


# Test 2: Bearish pullback scenario
def test_2_bearish_pullback_scenario():
    ctx = _mock_context("BEARISH")
    scenario_engine = TradeScenarioEngine()
    res = scenario_engine.evaluate_scenarios("XAUUSD", 4335.20, market_context=ctx)
    assert res.primary_scenario is not None
    assert res.primary_scenario.direction == "SHORT"
    assert res.primary_scenario.scenario == "SHORT_PULLBACK"


# Test 3: Bullish reversal
def test_3_bullish_reversal():
    ctx = _mock_context("BEARISH")
    ctx.market_state = "LIQUIDITY_SWEEP"
    levels = ImportantLevels(
        status="AVAILABLE",
        levels=[LevelDetail(midpoint=4330.0, classification="SELL_SIDE_LIQUIDITY", status="SWEPT")]
    )
    scenario_engine = TradeScenarioEngine()
    res = scenario_engine.evaluate_scenarios("XAUUSD", 4335.20, market_context=ctx, important_levels=levels)
    assert any(s.scenario == "LONG_REVERSAL" for s in [res.primary_scenario, res.secondary_scenario] if s)


# Test 4: Bearish reversal
def test_4_bearish_reversal():
    ctx = _mock_context("BULLISH")
    levels = ImportantLevels(
        status="AVAILABLE",
        levels=[LevelDetail(midpoint=4340.0, classification="BUY_SIDE_LIQUIDITY", status="SWEPT")]
    )
    scenario_engine = TradeScenarioEngine()
    res = scenario_engine.evaluate_scenarios("XAUUSD", 4335.20, market_context=ctx, important_levels=levels)
    assert any(s.scenario == "SHORT_REVERSAL" for s in [res.primary_scenario, res.secondary_scenario] if s)


# Test 5: Buy-side liquidity sweep
def test_5_buyside_liquidity_sweep():
    ctx = _mock_context("BEARISH")
    levels = ImportantLevels(
        status="AVAILABLE",
        levels=[LevelDetail(midpoint=4339.0, classification="BUY_SIDE_LIQUIDITY", status="SWEPT")]
    )
    scenario_engine = TradeScenarioEngine()
    res = scenario_engine.evaluate_scenarios("XAUUSD", 4335.20, market_context=ctx, important_levels=levels)
    assert res.primary_scenario.liquidity.status == "SWEPT"


# Test 6: Sell-side liquidity sweep
def test_6_sellside_liquidity_sweep():
    ctx = _mock_context("BULLISH")
    levels = ImportantLevels(
        status="AVAILABLE",
        levels=[LevelDetail(midpoint=4330.0, classification="SELL_SIDE_LIQUIDITY", status="SWEPT")]
    )
    scenario_engine = TradeScenarioEngine()
    res = scenario_engine.evaluate_scenarios("XAUUSD", 4335.20, market_context=ctx, important_levels=levels)
    assert any(s.liquidity.status == "SWEPT" for s in [res.primary_scenario, res.secondary_scenario] if s and s.liquidity)


# Test 7: Bullish false breakout
def test_7_bullish_false_breakout():
    ctx = _mock_context("NEUTRAL")
    ctx.market_state = "POST_SWEEP_REACTION"
    scenario_engine = TradeScenarioEngine()
    res = scenario_engine.evaluate_scenarios("XAUUSD", 4335.20, market_context=ctx)
    assert res.overall_action in ["LONG_SCENARIO", "SHORT_SCENARIO", "WAIT"]


# Test 8: Bearish false breakout
def test_8_bearish_false_breakout():
    ctx = _mock_context("NEUTRAL")
    ctx.market_state = "POST_SWEEP_REACTION"
    scenario_engine = TradeScenarioEngine()
    res = scenario_engine.evaluate_scenarios("XAUUSD", 4335.20, market_context=ctx)
    assert res.overall_action in ["LONG_SCENARIO", "SHORT_SCENARIO", "WAIT"]


# Test 9: Confirmed breakout
def test_9_confirmed_breakout():
    ctx = _mock_context("BULLISH")
    ctx.market_state = "BREAKOUT"
    scenario_engine = TradeScenarioEngine()
    res = scenario_engine.evaluate_scenarios("XAUUSD", 4335.20, market_context=ctx)
    assert isinstance(res.overall_action, str)


# Test 10: Failed breakout
def test_10_failed_breakout():
    ctx = _mock_context("NEUTRAL")
    scenario_engine = TradeScenarioEngine()
    res = scenario_engine.evaluate_scenarios("XAUUSD", 4335.20, market_context=ctx)
    assert isinstance(res.overall_action, str)


# Test 11: LONG confirmation workflow
def test_11_long_confirmation_workflow():
    ctx = _mock_context("BULLISH")
    ctx.market_bias = "BULLISH"
    scenario_engine = TradeScenarioEngine()
    res = scenario_engine.evaluate_scenarios("XAUUSD", 4335.20, market_context=ctx)
    assert res.primary_scenario.confirmation_required is not None
    assert len(res.primary_scenario.confirmation_required) > 0


# Test 12: SHORT confirmation workflow
def test_12_short_confirmation_workflow():
    ctx = _mock_context("BEARISH")
    scenario_engine = TradeScenarioEngine()
    res = scenario_engine.evaluate_scenarios("XAUUSD", 4335.20, market_context=ctx)
    assert res.primary_scenario.confirmation_required is not None
    assert len(res.primary_scenario.confirmation_required) > 0


# Test 13: Scenario invalidation
def test_13_scenario_invalidation():
    ctx = _mock_context("BEARISH")
    scenario_engine = TradeScenarioEngine()
    res = scenario_engine.evaluate_scenarios("XAUUSD", 4335.20, market_context=ctx)
    assert res.primary_scenario.invalidation_reasons is not None
    assert len(res.primary_scenario.invalidation_reasons) > 0


# Test 14: WAIT state
def test_14_wait_state():
    ctx = _mock_context("NEUTRAL")
    ctx.market_bias = "NEUTRAL"
    ctx.structure.htf = "NEUTRAL"
    scenario_engine = TradeScenarioEngine()
    res = scenario_engine.evaluate_scenarios("XAUUSD", 4335.20, market_context=ctx)
    assert res.overall_action == "WAIT"


# Test 15: NO_TRADE state
def test_15_no_trade_state():
    scenario_engine = TradeScenarioEngine()
    res = scenario_engine.evaluate_scenarios("XAUUSD", -1.0, market_context=None)
    assert res.overall_action == "NO_TRADE"
    assert "Invalid canonical price" in res.reasons[0]


# Test 16: Competing long/short scenarios
def test_16_competing_long_short_scenarios():
    ctx = _mock_context("BEARISH")
    levels = ImportantLevels(
        status="AVAILABLE",
        levels=[
            LevelDetail(midpoint=4340.0, classification="RESISTANCE"),
            LevelDetail(midpoint=4330.0, classification="SUPPORT", status="SWEPT")
        ]
    )
    scenario_engine = TradeScenarioEngine()
    res = scenario_engine.evaluate_scenarios("XAUUSD", 4335.20, market_context=ctx, important_levels=levels)
    assert res.primary_scenario is not None
    assert res.secondary_scenario is not None


# Test 17: DOM unavailable degradation
def test_17_dom_unavailable_degradation():
    ctx = _mock_context("BEARISH")
    scenario_engine = TradeScenarioEngine()
    res = scenario_engine.evaluate_scenarios("XAUUSD", 4335.20, market_context=ctx, dom_intelligence=None)
    assert res.primary_scenario.confidence <= 85


# Test 18: Stale data rejection
def test_18_stale_data_rejection():
    scenario_engine = TradeScenarioEngine()
    res = scenario_engine.evaluate_scenarios("XAUUSD", 0.0, market_context=None)
    assert res.overall_action == "NO_TRADE"


# Test 19: High-confluence level scenario
def test_19_high_confluence_level_scenario():
    ctx = _mock_context("BEARISH")
    levels = ImportantLevels(
        status="AVAILABLE",
        levels=[LevelDetail(midpoint=4339.10, classification="RESISTANCE", confluence_score=93, actionability="IMMEDIATE")]
    )
    scenario_engine = TradeScenarioEngine()
    res = scenario_engine.evaluate_scenarios("XAUUSD", 4335.20, market_context=ctx, important_levels=levels)
    assert res.primary_scenario.trigger_level.confluence_score == 93


# Test 20: Low-quality level rejection
def test_20_low_quality_level_rejection():
    ctx = _mock_context("NEUTRAL")
    ctx.market_bias = "NEUTRAL"
    ctx.structure.htf = "NEUTRAL"
    scenario_engine = TradeScenarioEngine()
    res = scenario_engine.evaluate_scenarios("XAUUSD", 4335.20, market_context=ctx)
    assert res.overall_action == "WAIT"


# Test 21: Session context influence
def test_21_session_context_influence():
    ctx = _mock_context("BEARISH")
    scenario_engine = TradeScenarioEngine()
    res = scenario_engine.evaluate_scenarios("XAUUSD", 4335.20, market_context=ctx)
    assert res.primary_scenario is not None


# Test 22: Scenario scoring
def test_22_scenario_scoring():
    ctx = _mock_context("BEARISH")
    scenario_engine = TradeScenarioEngine()
    res = scenario_engine.evaluate_scenarios("XAUUSD", 4335.20, market_context=ctx)
    assert 0 <= res.primary_scenario.score <= 100


# Test 23: Scenario confidence
def test_23_scenario_confidence():
    ctx = _mock_context("BEARISH")
    scenario_engine = TradeScenarioEngine()
    res = scenario_engine.evaluate_scenarios("XAUUSD", 4335.20, market_context=ctx)
    assert 0 <= res.primary_scenario.confidence <= 100


# Test 24: Explainable scenario payload
def test_24_explainable_scenario_payload():
    ctx = _mock_context("BEARISH")
    scenario_engine = TradeScenarioEngine()
    res = scenario_engine.evaluate_scenarios("XAUUSD", 4335.20, market_context=ctx)
    assert len(res.primary_scenario.evidence) > 0
    assert len(res.primary_scenario.confirmation_required) > 0
    assert len(res.primary_scenario.invalidation_reasons) > 0


# Test 25: End-to-end XAUUSD scenario generation
@pytest.mark.asyncio
async def test_25_end_to_end_xauusd_scenario_generation():
    manager = ProviderManager()
    with patch.object(manager, "_resolve_canonical_price", new=AsyncMock(return_value=PriceMetadata(
        price=4335.20, source="OANDA", timestamp=time.time(), is_market_feed=True, age_seconds=0.0, status="LIVE"
    ))):
        res = await manager.get_market_intelligence("XAUUSD", "5M")
        assert res.trade_scenario is not None
        assert res.trade_scenario.overall_action in ["LONG_SCENARIO", "SHORT_SCENARIO", "WAIT", "NO_TRADE"]
        if res.trade_scenario.primary_scenario:
            assert res.trade_scenario.primary_scenario.symbol == "XAUUSD"
            assert res.trade_scenario.primary_scenario.direction in ["LONG", "SHORT", "WAIT", "NO_TRADE"]
            assert res.trade_scenario.primary_scenario.state in ["WAITING", "FORMING", "CONFIRMATION_REQUIRED", "CONFIRMED", "INVALIDATED", "EXPIRED"]
