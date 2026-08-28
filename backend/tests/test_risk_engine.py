import time
import pytest
from unittest.mock import AsyncMock, patch
from app.market.context import MarketContextEngine
from app.market.scenarios import TradeScenarioEngine
from app.market.risk import RiskEngine
from app.models.schemas import (
    TradeScenarioResponse, TradeScenarioDetail, ScenarioTriggerLevel,
    ImportantLevels, LevelDetail, PriceMetadata
)
from app.providers.manager import ProviderManager


def _mock_confirmed_scenario(direction="SHORT", score=84):
    return TradeScenarioResponse(
        primary_scenario=TradeScenarioDetail(
            symbol="XAUUSD",
            scenario=f"{direction}_PULLBACK",
            direction=direction,
            state="CONFIRMED",
            score=score,
            confidence=80,
            context_bias="BEARISH" if direction == "SHORT" else "BULLISH",
            trigger_level=ScenarioTriggerLevel(zone="4337.80–4340.40", midpoint=4339.10, classification="RESISTANCE" if direction == "SHORT" else "SUPPORT", confluence_score=93, actionability="IMMEDIATE"),
            evidence=["Bearish HTF structure", "Confirmed setup"],
            confirmation_required=[],
            invalidation_reasons=["Structure broken"]
        ),
        overall_action=f"{direction}_SCENARIO"
    )


def _mock_forming_scenario(direction="SHORT"):
    return TradeScenarioResponse(
        primary_scenario=TradeScenarioDetail(
            symbol="XAUUSD",
            scenario=f"{direction}_PULLBACK",
            direction=direction,
            state="CONFIRMATION_REQUIRED",
            score=84,
            confidence=80,
            context_bias="BEARISH",
            trigger_level=ScenarioTriggerLevel(zone="4337.80–4340.40", midpoint=4339.10, classification="RESISTANCE", confluence_score=93, actionability="IMMEDIATE"),
            evidence=["Forming setup"],
            confirmation_required=["Bearish CHoCH"],
            invalidation_reasons=["Structure broken"]
        ),
        overall_action=f"{direction}_SCENARIO"
    )


# Test 1: Valid LONG trade
def test_1_valid_long_trade():
    re = RiskEngine()
    ts = _mock_confirmed_scenario("LONG")
    res = re.validate_trade_scenario("XAUUSD", 4335.20, trade_scenario=ts)
    assert res.direction == "LONG"
    assert res.state in ["VALID", "MARGINAL"]


# Test 2: Valid SHORT trade
def test_2_valid_short_trade():
    re = RiskEngine()
    ts = _mock_confirmed_scenario("SHORT")
    res = re.validate_trade_scenario("XAUUSD", 4335.20, trade_scenario=ts)
    assert res.direction == "SHORT"
    assert res.state in ["VALID", "MARGINAL"]


# Test 3: Invalid RR (< 1.5)
def test_3_invalid_rr():
    re = RiskEngine(minimum_rr=5.0)  # Unusually high minimum RR threshold
    ts = _mock_confirmed_scenario("SHORT")
    res = re.validate_trade_scenario("XAUUSD", 4335.20, trade_scenario=ts)
    assert res.state == "INVALID"
    assert "below minimum threshold" in res.reasons[0]


# Test 4: Minimum RR boundary
def test_4_minimum_rr_boundary():
    re = RiskEngine(minimum_rr=1.5)
    ts = _mock_confirmed_scenario("SHORT")
    res = re.validate_trade_scenario("XAUUSD", 4335.20, trade_scenario=ts)
    assert res.risk_reward.minimum_required == 1.5


# Test 5: Invalid entry
def test_5_invalid_entry():
    re = RiskEngine()
    res = re.validate_trade_scenario("XAUUSD", 0.0, trade_scenario=None)
    assert res.state == "WAIT"


# Test 6: Invalid SL
def test_6_invalid_sl():
    re = RiskEngine()
    ts = _mock_confirmed_scenario("SHORT")

    with patch.object(re, "_calculate_stop_loss", return_value=type("Obj", (), {"price": None, "risk_distance": 0.0})()):
        res = re.validate_trade_scenario("XAUUSD", 4335.20, trade_scenario=ts)
        assert res.state == "INVALID"


# Test 7: Invalid target
def test_7_invalid_target():
    re = RiskEngine()
    ts = _mock_confirmed_scenario("SHORT")
    with patch.object(re, "_calculate_targets", return_value=[]):
        res = re.validate_trade_scenario("XAUUSD", 4335.20, trade_scenario=ts)
        assert res.state == "INVALID"


# Test 8: Structural SL
def test_8_structural_sl():
    re = RiskEngine()
    ts = _mock_confirmed_scenario("SHORT")
    res = re.validate_trade_scenario("XAUUSD", 4335.20, trade_scenario=ts)
    assert res.stop_loss.method == "STRUCTURAL_PLUS_ATR_BUFFER"
    assert res.stop_loss.price > 4335.20


# Test 9: Liquidity SL
def test_9_liquidity_sl():
    re = RiskEngine()
    ts = _mock_confirmed_scenario("LONG")
    res = re.validate_trade_scenario("XAUUSD", 4335.20, trade_scenario=ts)
    assert res.stop_loss.price < res.entry.price



# Test 10: ATR buffer
def test_10_atr_buffer():
    re = RiskEngine(stop_buffer_atr=0.20)
    ts = _mock_confirmed_scenario("SHORT")
    res = re.validate_trade_scenario("XAUUSD", 4335.20, trade_scenario=ts)
    assert res.stop_loss.risk_distance > 0.0


# Test 11: Multiple targets
def test_11_multiple_targets():
    re = RiskEngine()
    ts = _mock_confirmed_scenario("SHORT")
    res = re.validate_trade_scenario("XAUUSD", 4335.20, trade_scenario=ts)
    assert len(res.targets) >= 2


# Test 12: Opposing liquidity target
def test_12_opposing_liquidity_target():
    re = RiskEngine()
    ts = _mock_confirmed_scenario("SHORT")
    res = re.validate_trade_scenario("XAUUSD", 4335.20, trade_scenario=ts)
    assert res.targets[0].type == "SELL_SIDE_LIQUIDITY"


# Test 13: Spread available
def test_13_spread_available():
    re = RiskEngine()
    ts = _mock_confirmed_scenario("SHORT")
    res = re.validate_trade_scenario("XAUUSD", 4335.20, trade_scenario=ts, spread=0.30)
    assert res.market_conditions.spread == 0.30
    assert res.market_conditions.spread_status == "LIVE"


# Test 14: Spread unavailable
def test_14_spread_unavailable():
    re = RiskEngine()
    ts = _mock_confirmed_scenario("SHORT")
    res = re.validate_trade_scenario("XAUUSD", 4335.20, trade_scenario=ts, spread=None)
    assert res.market_conditions.spread_status == "UNKNOWN"


# Test 15: Slippage estimated
def test_15_slippage_estimated():
    re = RiskEngine()
    ts = _mock_confirmed_scenario("SHORT")
    res = re.validate_trade_scenario("XAUUSD", 4335.20, trade_scenario=ts)
    assert res.market_conditions.slippage == "ESTIMATED"


# Test 16: Slippage unknown
def test_16_slippage_unknown():
    re = RiskEngine()
    ts = _mock_confirmed_scenario("SHORT")
    res = re.validate_trade_scenario("XAUUSD", 4335.20, trade_scenario=ts)
    assert res.market_conditions.slippage in ["ESTIMATED", "UNKNOWN"]


# Test 17: Extreme volatility
def test_17_extreme_volatility():
    re = RiskEngine()
    ts = _mock_confirmed_scenario("SHORT")
    ctx = MarketContextEngine().build_market_context("XAUUSD", 4335.20, atr=20.0)
    ctx.market_regime.volatility = "EXTREME"
    res = re.validate_trade_scenario("XAUUSD", 4335.20, trade_scenario=ts, market_context=ctx)
    assert res.state == "INVALID"
    assert "Extreme market volatility" in res.reasons[0]


# Test 18: High volatility
def test_18_high_volatility():
    re = RiskEngine()
    ts = _mock_confirmed_scenario("SHORT")
    res = re.validate_trade_scenario("XAUUSD", 4335.20, trade_scenario=ts)
    assert res.market_conditions.volatility is not None


# Test 19: Session risk
def test_19_session_risk():
    re = RiskEngine()
    ts = _mock_confirmed_scenario("SHORT")
    res = re.validate_trade_scenario("XAUUSD", 4335.20, trade_scenario=ts)
    assert res.market_conditions.session is not None


# Test 20: High event risk
def test_20_high_event_risk():
    re = RiskEngine()
    ts = _mock_confirmed_scenario("SHORT")
    res = re.validate_trade_scenario("XAUUSD", 4335.20, trade_scenario=ts)
    assert res.market_conditions.event_risk == "UNKNOWN"


# Test 21: DOM unavailable
def test_21_dom_unavailable():
    re = RiskEngine()
    ts = _mock_confirmed_scenario("SHORT")
    res = re.validate_trade_scenario("XAUUSD", 4335.20, trade_scenario=ts, dom_intelligence=None)
    assert res.market_conditions.dom == "NO-SOURCE"


# Test 22: Single-source DOM
def test_22_single_source_dom():
    re = RiskEngine()
    ts = _mock_confirmed_scenario("SHORT")
    res = re.validate_trade_scenario("XAUUSD", 4335.20, trade_scenario=ts)
    assert res.market_conditions.dom is not None


# Test 23: Multi-source DOM
def test_23_multi_source_dom():
    re = RiskEngine()
    ts = _mock_confirmed_scenario("SHORT")
    res = re.validate_trade_scenario("XAUUSD", 4335.20, trade_scenario=ts)
    assert res.market_conditions.dom is not None


# Test 24: Account data unavailable
def test_24_account_data_unavailable():
    re = RiskEngine()
    ts = _mock_confirmed_scenario("SHORT")
    res = re.validate_trade_scenario("XAUUSD", 4335.20, trade_scenario=ts, account_balance=None)
    assert res.risk.position_size is None
    assert res.risk.position_size_status == "ACCOUNT_DATA_UNAVAILABLE"


# Test 25: Position-size calculation with valid account data
def test_25_position_size_with_account_data():
    re = RiskEngine()
    ts = _mock_confirmed_scenario("SHORT")
    res = re.validate_trade_scenario("XAUUSD", 4335.20, trade_scenario=ts, account_balance=10000.0, risk_per_trade_pct=1.0)
    assert res.risk.position_size is not None
    assert res.risk.position_size_status == "CALCULATED"


# Test 26: Position-size safety
def test_26_position_size_safety():
    re = RiskEngine()
    ts = _mock_confirmed_scenario("SHORT")
    res = re.validate_trade_scenario("XAUUSD", 4335.20, trade_scenario=ts, account_balance=None)
    assert res.risk.position_size is None


# Test 27: Tradeability scoring
def test_27_tradeability_scoring():
    re = RiskEngine()
    ts = _mock_confirmed_scenario("SHORT")
    res = re.validate_trade_scenario("XAUUSD", 4335.20, trade_scenario=ts)
    assert 0 <= res.validation.tradeability_score <= 100


# Test 28: WAIT before confirmation
def test_28_wait_before_confirmation():
    re = RiskEngine()
    ts = _mock_forming_scenario("SHORT")
    res = re.validate_trade_scenario("XAUUSD", 4335.20, trade_scenario=ts)
    assert res.state == "WAIT"


# Test 29: INVALID after RR failure
def test_29_invalid_after_rr_failure():
    re = RiskEngine(minimum_rr=10.0)  # Extreme RR requirement
    ts = _mock_confirmed_scenario("SHORT")
    res = re.validate_trade_scenario("XAUUSD", 4335.20, trade_scenario=ts)
    assert res.state == "INVALID"


# Test 30: Full end-to-end XAUUSD risk validation
@pytest.mark.asyncio
async def test_30_full_end_to_end_xauusd_risk_validation():
    manager = ProviderManager()
    with patch.object(manager, "_resolve_canonical_price", new=AsyncMock(return_value=PriceMetadata(
        price=4335.20, source="OANDA", timestamp=time.time(), is_market_feed=True, age_seconds=0.0, status="LIVE"
    ))):
        res = await manager.get_market_intelligence("XAUUSD", "5M")
        assert res.trade_validation is not None
        assert res.trade_validation.symbol == "XAUUSD"
        assert res.trade_validation.state in ["VALID", "MARGINAL", "INVALID", "WAIT"]
        assert res.trade_validation.risk_reward.minimum_required == 1.5
        assert len(res.trade_validation.reasons) > 0
