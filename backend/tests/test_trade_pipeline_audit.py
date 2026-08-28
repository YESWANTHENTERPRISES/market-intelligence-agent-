import pytest
from app.replay.models import ScenarioEvent, TradePlanEvent
from app.replay.pipeline_auditor import TradePipelineAuditor


def test_scenario_reaches_risk_engine():
    sc = ScenarioEvent(
        timestamp="2026-01-05T10:00:00Z",
        symbol="XAUUSD",
        scenario="SHORT_PULLBACK",
        direction="SHORT",
        state="CONFIRMED",
        price=4330.0,
        score=85,
        confidence=80,
        trigger_level=4335.0,
        evidence=["Bearish CHoCH confirmed", "Fair Value Gap retest"]
    )
    plan = TradePlanEvent(
        trade_id="T1",
        timestamp="2026-01-05T10:00:00Z",
        symbol="XAUUSD",
        scenario="SHORT_PULLBACK",
        direction="SHORT",
        state="VALID",
        entry_price=4330.0,
        sl_price=4335.0,
        tp1_price=4320.0,
        rr=2.0
    )
    report = TradePipelineAuditor.audit_pipeline([sc], [plan], is_real_data=True, dom_available=False)
    assert report.funnel.scenario_generated == 1
    assert report.funnel.scenario_confirmation_passed == 1
    assert report.funnel.risk_validation_reached == 1
    assert report.funnel.trade_valid == 1


def test_confirmation_rejection_reason():
    sc = ScenarioEvent(
        timestamp="2026-01-05T10:00:00Z",
        symbol="XAUUSD",
        scenario="SHORT_PULLBACK",
        direction="SHORT",
        state="FORMING",
        price=4330.0,
        score=75,
        confidence=65,
        trigger_level=4335.0,
        evidence=["CHoCH required"]
    )
    report = TradePipelineAuditor.audit_pipeline([sc], [], is_real_data=True, dom_available=False)
    assert report.funnel.scenario_generated == 1
    assert report.funnel.scenario_confirmation_failed == 1
    assert "MISSING_CHoCH" in report.short_pullback_audit.rejection_reasons


def test_missing_trigger_level():
    sc = ScenarioEvent(
        timestamp="2026-01-05T10:00:00Z",
        symbol="XAUUSD",
        scenario="LONG_PULLBACK",
        direction="LONG",
        state="FORMING",
        price=4300.0,
        score=70,
        confidence=60,
        trigger_level=None,
        evidence=[]
    )
    report = TradePipelineAuditor.audit_pipeline([sc], [], is_real_data=True, dom_available=False)
    assert report.target_availability.missing_trigger_level_pct == 100.0
    assert report.long_pullback_audit.rejection_reasons.get("NO_TRIGGER_LEVEL") == 1


def test_missing_sl():
    sc = ScenarioEvent(
        timestamp="2026-01-05T10:00:00Z",
        symbol="XAUUSD",
        scenario="SHORT_PULLBACK",
        direction="SHORT",
        state="CONFIRMED",
        price=4330.0,
        score=85,
        confidence=80,
        trigger_level=4335.0
    )
    plan = TradePlanEvent(
        trade_id="T1",
        timestamp="2026-01-05T10:00:00Z",
        symbol="XAUUSD",
        scenario="SHORT_PULLBACK",
        direction="SHORT",
        state="INVALID",
        entry_price=4330.0,
        sl_price=None,
        tp1_price=4320.0,
        reasons=["INVALID_SL_GEOMETRY"]
    )
    report = TradePipelineAuditor.audit_pipeline([sc], [plan], is_real_data=True, dom_available=False)
    assert report.target_availability.missing_invalidation_level_pct == 100.0
    assert report.risk_engine_audit.invalid_sl_geometry == 1


def test_missing_tp1():
    sc = ScenarioEvent(
        timestamp="2026-01-05T10:00:00Z",
        symbol="XAUUSD",
        scenario="SHORT_PULLBACK",
        direction="SHORT",
        state="CONFIRMED",
        price=4330.0,
        score=85,
        confidence=80,
        trigger_level=4335.0
    )
    plan = TradePlanEvent(
        trade_id="T1",
        timestamp="2026-01-05T10:00:00Z",
        symbol="XAUUSD",
        scenario="SHORT_PULLBACK",
        direction="SHORT",
        state="INVALID",
        entry_price=4330.0,
        sl_price=4335.0,
        tp1_price=None,
        reasons=["NO_TP1"]
    )
    report = TradePipelineAuditor.audit_pipeline([sc], [plan], is_real_data=True, dom_available=False)
    assert report.target_availability.missing_tp1_pct == 100.0


def test_rr_below_threshold():
    sc = ScenarioEvent(
        timestamp="2026-01-05T10:00:00Z",
        symbol="XAUUSD",
        scenario="SHORT_PULLBACK",
        direction="SHORT",
        state="CONFIRMED",
        price=4330.0,
        score=85,
        confidence=80,
        trigger_level=4335.0
    )
    plan = TradePlanEvent(
        trade_id="T1",
        timestamp="2026-01-05T10:00:00Z",
        symbol="XAUUSD",
        scenario="SHORT_PULLBACK",
        direction="SHORT",
        state="INVALID",
        entry_price=4330.0,
        sl_price=4335.0,
        tp1_price=4326.0,  # RR = 4.0 / 5.0 = 0.8 (< 1.5)
        rr=0.8,
        reasons=["RR_BELOW_MINIMUM"]
    )
    report = TradePipelineAuditor.audit_pipeline([sc], [plan], is_real_data=True, dom_available=False)
    assert report.risk_engine_audit.rr_below_1_5 == 1
    assert report.rr_distribution.buckets["0.5-1.0"] == 1


def test_valid_rr_calculation():
    sc = ScenarioEvent(
        timestamp="2026-01-05T10:00:00Z",
        symbol="XAUUSD",
        scenario="SHORT_PULLBACK",
        direction="SHORT",
        state="CONFIRMED",
        price=4330.0,
        score=85,
        confidence=80,
        trigger_level=4335.0
    )
    plan = TradePlanEvent(
        trade_id="T1",
        timestamp="2026-01-05T10:00:00Z",
        symbol="XAUUSD",
        scenario="SHORT_PULLBACK",
        direction="SHORT",
        state="INVALID",
        entry_price=4330.0,
        sl_price=4335.0,
        tp1_price=4324.0,  # RR = 6.0 / 5.0 = 1.2
        rr=1.2
    )
    report = TradePipelineAuditor.audit_pipeline([sc], [plan], is_real_data=True, dom_available=False)
    assert report.rr_distribution.min_rr == 1.2
    assert report.rr_distribution.max_rr == 1.2
    assert report.rr_distribution.buckets["1.0-1.5"] == 1


def test_dom_unavailable_handling():
    report = TradePipelineAuditor.audit_pipeline([], [], is_real_data=True, dom_available=False)
    assert report.dom_dependency.dom_available is False
    assert report.dom_dependency.status == "DOM_DEPENDENCY_BLOCKING_TRADES"


def test_short_pullback_rejection_accounting():
    sc1 = ScenarioEvent(
        timestamp="2026-01-05T10:00:00Z",
        symbol="XAUUSD",
        scenario="SHORT_PULLBACK",
        direction="SHORT",
        state="FORMING",
        price=4330.0,
        score=75,
        confidence=65,
        trigger_level=4335.0,
        evidence=["displacement missing"]
    )
    sc2 = ScenarioEvent(
        timestamp="2026-01-05T10:05:00Z",
        symbol="XAUUSD",
        scenario="SHORT_PULLBACK",
        direction="SHORT",
        state="FORMING",
        price=4332.0,
        score=75,
        confidence=65,
        trigger_level=4335.0,
        evidence=["sweep missing"]
    )
    report = TradePipelineAuditor.audit_pipeline([sc1, sc2], [], is_real_data=True, dom_available=False)
    assert report.short_pullback_audit.total_generated == 2
    assert report.short_pullback_audit.rejected == 2
    assert "MISSING_DISPLACEMENT" in report.short_pullback_audit.rejection_reasons
    assert "MISSING_LIQUIDITY_SWEEP" in report.short_pullback_audit.rejection_reasons


def test_long_pullback_rejection_accounting():
    sc1 = ScenarioEvent(
        timestamp="2026-01-05T10:00:00Z",
        symbol="XAUUSD",
        scenario="LONG_PULLBACK",
        direction="LONG",
        state="FORMING",
        price=4300.0,
        score=70,
        confidence=60,
        trigger_level=4305.0,
        evidence=["CHoCH missing"]
    )
    report = TradePipelineAuditor.audit_pipeline([sc1], [], is_real_data=True, dom_available=False)
    assert report.long_pullback_audit.total_generated == 1
    assert report.long_pullback_audit.rejected == 1
    assert "MISSING_CHoCH" in report.long_pullback_audit.rejection_reasons


def test_full_funnel_accounting():
    sc1 = ScenarioEvent(
        timestamp="2026-01-05T10:00:00Z",
        symbol="XAUUSD",
        scenario="SHORT_PULLBACK",
        direction="SHORT",
        state="FORMING",
        price=4330.0,
        score=70,
        confidence=60
    )
    sc2 = ScenarioEvent(
        timestamp="2026-01-05T10:05:00Z",
        symbol="XAUUSD",
        scenario="SHORT_PULLBACK",
        direction="SHORT",
        state="CONFIRMED",
        price=4332.0,
        score=85,
        confidence=80,
        trigger_level=4335.0
    )
    plan2 = TradePlanEvent(
        trade_id="T2",
        timestamp="2026-01-05T10:05:00Z",
        symbol="XAUUSD",
        scenario="SHORT_PULLBACK",
        direction="SHORT",
        state="VALID",
        entry_price=4332.0,
        sl_price=4337.0,
        tp1_price=4322.0,  # RR = 10 / 5 = 2.0 (>= 1.5)
        rr=2.0
    )
    report = TradePipelineAuditor.audit_pipeline([sc1, sc2], [plan2], is_real_data=True, dom_available=False)
    assert report.funnel.scenario_generated == 2
    assert report.funnel.scenario_confirmation_passed == 1
    assert report.funnel.scenario_confirmation_failed == 1
    assert report.funnel.risk_validation_reached == 1
    assert report.funnel.trade_valid == 1
