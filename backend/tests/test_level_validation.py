import pytest
from app.providers.dom.normalizer import classify_freshness
from app.providers.dom.models import SourceSnapshot, SourceStatus
from app.market.price_areas import price_area_clusterer

def test_10_source_unavailable():
    snap = SourceSnapshot(
        source_id="FXCM",
        source_name="FXCM",
        status=SourceStatus.UNAVAILABLE,
        observed_timestamp=0.0,
        freshness_seconds=0.0,
        freshness_label="UNAVAILABLE",
        included_in_aggregation=False
    )
    status, fresh_label = classify_freshness(snap, 100.0)
    assert status == SourceStatus.UNAVAILABLE
    assert fresh_label == "UNAVAILABLE"

def test_12_level_invalidation():
    zone = {
        "zone": "4438–4440",
        "zone_low": 4438.0,
        "zone_high": 4440.0,
        "midpoint": 4439.0,
        "classification": "RESISTANCE",
        "status": "ACTIVE",
        "evidence": ["1H swing high"]
    }
    atr = 10.0
    # Decisive break above 4440 + 5.0 (4445.0) -> current price 4448.0
    updated_zone = price_area_clusterer.evaluate_level_transitions(
        zone=zone, current_price=4448.0, atr=atr
    )

    assert updated_zone["status"] == "BROKEN"
    assert updated_zone["classification"] == "BROKEN_RESISTANCE"

def test_13_broken_resistance_becomes_support_after_confirmation():
    zone = {
        "zone": "4438–4440",
        "zone_low": 4438.0,
        "zone_high": 4440.0,
        "midpoint": 4439.0,
        "classification": "BROKEN_RESISTANCE",
        "status": "BROKEN",
        "evidence": ["Decisive upside breakout confirmed"]
    }
    atr = 10.0
    # Price retests 4439.0 and confirms defense
    retested_zone = price_area_clusterer.evaluate_level_transitions(
        zone=zone, current_price=4439.0, atr=atr, confirmed_retest=True
    )

    assert retested_zone["classification"] == "SUPPORT"
    assert retested_zone["status"] == "ACTIVE"
    assert any("converted to Support" in ev for ev in retested_zone["evidence"])
