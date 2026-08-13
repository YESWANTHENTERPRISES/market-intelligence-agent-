import time
import pytest
from app.providers.dom.models import SourceSnapshot, SourceStatus, PriceLevel, DOMIntelligenceData
from app.providers.dom.normalizer import (
    classify_freshness,
    calculate_basis,
    normalize_futures_price,
    score_relative_depth,
    renormalize_weights
)
from app.providers.dom.engine import dom_engine

def test_source_freshness_classification():
    now = time.time()
    
    # 1. LIVE snapshot
    live_snap = SourceSnapshot(
        source_id="TEST", source_name="Test", status=SourceStatus.LIVE,
        observed_timestamp=now - 5.0
    )
    status, label = classify_freshness(live_snap, now)
    assert status == SourceStatus.LIVE
    assert label == "LIVE"

    # 2. DELAYED snapshot
    delayed_snap = SourceSnapshot(
        source_id="TEST", source_name="Test", status=SourceStatus.DELAYED,
        observed_timestamp=now - 900.0
    )
    status, label = classify_freshness(delayed_snap, now)
    assert status == SourceStatus.DELAYED
    assert label == "DELAYED 15M"

    # 3. STALE snapshot
    stale_snap = SourceSnapshot(
        source_id="TEST", source_name="Test", status=SourceStatus.LIVE,
        observed_timestamp=now - 120.0
    )
    status, label = classify_freshness(stale_snap, now)
    assert status == SourceStatus.STALE
    assert "STALE" in label

    # 4. UNAVAILABLE snapshot
    unavail_snap = SourceSnapshot(
        source_id="TEST", source_name="Test", status=SourceStatus.UNAVAILABLE,
        observed_timestamp=now
    )
    status, label = classify_freshness(unavail_snap, now)
    assert status == SourceStatus.UNAVAILABLE
    assert label == "UNAVAILABLE"

def test_comex_spot_basis_and_stale_rejection():
    now = time.time()

    # Valid basis
    basis, label = calculate_basis(4432.80, 4431.00, now, now)
    assert basis == pytest.approx(1.80, rel=1e-3)
    assert label == "+$1.80"

    # Stale timestamp rejection (> 60s divergence)
    basis, label = calculate_basis(4432.80, 4431.00, now - 120.0, now)
    assert basis is None
    assert label == "UNAVAILABLE"

def test_comex_price_coordinate_normalization():
    # futures_price = 4438.50, basis = 1.80 -> spot coordinate = 4436.70
    norm_price = normalize_futures_price(4438.50, 1.80)
    assert norm_price == pytest.approx(4436.70, rel=1e-3)

    # Missing basis -> returns raw price
    assert normalize_futures_price(4438.50, None) == 4438.50

def test_weight_renormalization():
    default_weights = {"COMEX": 0.35, "OANDA": 0.35, "DUKASCOPY": 0.30}
    
    # 1. All sources active
    active = ["COMEX", "OANDA", "DUKASCOPY"]
    weights = renormalize_weights(active, default_weights)
    assert sum(weights.values()) == pytest.approx(1.0)
    assert weights["COMEX"] == pytest.approx(0.35)

    # 2. COMEX missing
    active_no_comex = ["OANDA", "DUKASCOPY"]
    weights = renormalize_weights(active_no_comex, default_weights)
    assert sum(weights.values()) == pytest.approx(1.0)
    assert weights["OANDA"] == pytest.approx(0.35 / 0.65)
    assert weights["DUKASCOPY"] == pytest.approx(0.30 / 0.65)

def test_score_relative_depth():
    levels = [
        PriceLevel(price=4438.0, volume=500.0),
        PriceLevel(price=4439.0, volume=1000.0)
    ]
    scored = score_relative_depth(levels)
    assert scored[0].relative_score == pytest.approx(50.0)
    assert scored[1].relative_score == pytest.approx(100.0)

@pytest.mark.asyncio
async def test_dom_engine_full_build():
    dom_intel = await dom_engine.build_dom_intelligence("XAUUSD", 4431.00)
    assert isinstance(dom_intel, DOMIntelligenceData)
    assert "MULTI-SOURCE" in dom_intel.coverage
    assert len(dom_intel.sources) == 3
    assert dom_intel.retail_positioning in ["LONG", "SHORT", "NEUTRAL", "UNAVAILABLE"]
    assert dom_intel.futures_sell_wall in ["HIGH", "MODERATE", "LOW", "UNAVAILABLE"]
    assert dom_intel.divergence in ["HIGH", "MODERATE", "LOW", "NONE", "UNAVAILABLE"]
    assert dom_intel.data_quality in ["HIGH", "MODERATE", "LOW", "UNAVAILABLE"]

@pytest.mark.asyncio
async def test_dom_engine_dynamic_price_scaling():
    dom_intel = await dom_engine.build_dom_intelligence("XAUUSD", 4374.08)
    assert dom_intel.current_price == pytest.approx(4374.08, rel=1e-3)
    # Check liquidity ranges are scaled around 4374
    for lz in dom_intel.liquidity:
        parts = lz.price_range.split("–")
        if len(parts) == 2:
            low_p = float(parts[0])
            assert abs(low_p - 4374.08) < 50.0
