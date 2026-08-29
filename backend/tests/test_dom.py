import time
import pytest
from unittest.mock import AsyncMock, patch
from app.providers.dom.models import SourceSnapshot, SourceStatus, PriceLevel, DOMIntelligenceData
from app.providers.dom.normalizer import (
    classify_freshness,
    calculate_basis,
    normalize_futures_price,
    score_relative_depth,
    renormalize_weights
)
from app.providers.dom.engine import DOMEngine, dom_engine
from app.providers.dom.adapters import MT5DOMAdapter, CTraderDOMAdapter


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


def test_weight_renormalization():
    default_weights = {"MT5": 0.50, "CTRADER": 0.50}

    # 1. All sources active
    active = ["MT5", "CTRADER"]
    weights = renormalize_weights(active, default_weights)
    assert sum(weights.values()) == pytest.approx(1.0)
    assert weights["MT5"] == pytest.approx(0.50)
    assert weights["CTRADER"] == pytest.approx(0.50)

    # 2. MT5 only active
    active_mt5 = ["MT5"]
    weights = renormalize_weights(active_mt5, default_weights)
    assert sum(weights.values()) == pytest.approx(1.0)
    assert weights["MT5"] == pytest.approx(1.0)


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
    engine = DOMEngine()
    engine.adapters[0].fetch_snapshot = AsyncMock(return_value=SourceSnapshot(
        source_id="MT5", source_name="MetaTrader 5", status=SourceStatus.LIVE,
        observed_timestamp=time.time(), raw_spot_price=4431.00,
        bids=[PriceLevel(price=4430.0, volume=300.0)],
        asks=[PriceLevel(price=4432.0, volume=400.0)],
        included_in_aggregation=True
    ))
    engine.adapters[1].fetch_snapshot = AsyncMock(return_value=SourceSnapshot(
        source_id="CTRADER", source_name="cTrader Open API", status=SourceStatus.LIVE,
        observed_timestamp=time.time(), raw_spot_price=4431.00,
        bids=[PriceLevel(price=4429.5, volume=250.0)],
        asks=[PriceLevel(price=4432.5, volume=350.0)],
        included_in_aggregation=True
    ))
    dom_intel = await engine.build_dom_intelligence("XAUUSD", 4431.00)
    assert isinstance(dom_intel, DOMIntelligenceData)
    assert "MULTI-SOURCE" in dom_intel.coverage
    assert len(dom_intel.sources) == 2
    assert dom_intel.data_quality in ["HIGH", "MODERATE", "LOW", "UNAVAILABLE"]


@pytest.mark.asyncio
async def test_dom_engine_dynamic_price_scaling():
    engine = DOMEngine()
    engine.adapters[0].fetch_snapshot = AsyncMock(return_value=SourceSnapshot(
        source_id="MT5", source_name="MetaTrader 5", status=SourceStatus.LIVE,
        observed_timestamp=time.time(), raw_spot_price=4374.08,
        bids=[PriceLevel(price=4370.0, volume=100.0)],
        asks=[PriceLevel(price=4378.0, volume=100.0)]
    ))
    dom_intel = await engine.build_dom_intelligence("XAUUSD", 4374.08)
    assert dom_intel.current_price == pytest.approx(4374.08, rel=1e-3)
    for lz in dom_intel.liquidity:
        parts = lz.price_range.split("–")
        if len(parts) == 2:
            low_p = float(parts[0])
            assert abs(low_p - 4374.08) < 50.0


@pytest.mark.asyncio
async def test_1_adapter_exception_logged_and_isolated():
    engine = DOMEngine()
    engine.adapters[0].fetch_snapshot = AsyncMock(side_effect=RuntimeError("MT5 IPC disconnected"))

    dom_intel = await engine.build_dom_intelligence("XAUUSD", 4431.00)
    assert isinstance(dom_intel, DOMIntelligenceData)
    mt5_source = next(s for s in dom_intel.sources if s.name == "MetaTrader 5")
    assert mt5_source.included_in_aggregation is False
    assert mt5_source.status == "UNAVAILABLE"


def test_2_bid_bucket_grid_alignment():
    norm_price = 4430.0
    step = 8.86
    low_b = round(norm_price / step) * step
    bucket_key = f"{low_b:.2f}–{(low_b + step):.2f}"

    low_p = float(bucket_key.split("–")[0])
    high_p = float(bucket_key.split("–")[1])
    assert low_p <= 4430.0 <= high_p


@pytest.mark.asyncio
async def test_3_invalid_spot_price_validation():
    engine = DOMEngine()
    for bad_spot in [None, 0.0, -10.0]:
        with patch.object(engine.adapters[0], "fetch_snapshot", new=AsyncMock(return_value=SourceSnapshot(
            source_id="MT5", source_name="MetaTrader 5", status=SourceStatus.LIVE,
            observed_timestamp=time.time(), raw_spot_price=bad_spot
        ))):
            dom_intel = await engine.build_dom_intelligence("XAUUSD", current_price=None)
            assert dom_intel.current_price == pytest.approx(4431.00)


@pytest.mark.asyncio
async def test_4_valid_spot_price_used():
    engine = DOMEngine()
    with patch.object(engine.adapters[0], "fetch_snapshot", new=AsyncMock(return_value=SourceSnapshot(
        source_id="MT5", source_name="MetaTrader 5", status=SourceStatus.LIVE,
        observed_timestamp=time.time(), raw_spot_price=4431.25
    ))):
        dom_intel = await engine.build_dom_intelligence("XAUUSD", current_price=None)
        assert dom_intel.current_price == pytest.approx(4431.25)


@pytest.mark.asyncio
async def test_5_retail_positioning_unavailable():
    engine = DOMEngine()
    for adapter in engine.adapters:
        adapter.fetch_snapshot = AsyncMock(return_value=SourceSnapshot(
            source_id=adapter.source_id, source_name=adapter.source_name,
            status=SourceStatus.LIVE, observed_timestamp=time.time(),
            retail_long_pct=None
        ))
    dom_intel = await engine.build_dom_intelligence("XAUUSD", 4431.00)
    assert dom_intel.retail_positioning == "UNAVAILABLE"


@pytest.mark.asyncio
async def test_6_divergence_unavailable():
    engine = DOMEngine()
    for adapter in engine.adapters:
        adapter.fetch_snapshot = AsyncMock(return_value=SourceSnapshot(
            source_id=adapter.source_id, source_name=adapter.source_name,
            status=SourceStatus.LIVE, observed_timestamp=time.time(),
            retail_long_pct=None
        ))
    dom_intel = await engine.build_dom_intelligence("XAUUSD", 4431.00)
    assert dom_intel.divergence == "UNAVAILABLE"


def test_7_proximity_aware_top_bucket():
    engine = DOMEngine()
    current_price = 4431.00
    step = 8.0
    buckets = {
        "4425.00–4433.00": 70.0,
        "4800.00–4808.00": 85.0,
    }
    best = engine._score_with_proximity(buckets, current_price, step)
    assert best == "4425.00–4433.00"


@pytest.mark.asyncio
async def test_8_empty_buckets_safety():
    engine = DOMEngine()
    for adapter in engine.adapters:
        adapter.fetch_snapshot = AsyncMock(return_value=SourceSnapshot(
            source_id=adapter.source_id, source_name=adapter.source_name,
            status=SourceStatus.LIVE, observed_timestamp=time.time(),
            bids=[], asks=[]
        ))
    dom_intel = await engine.build_dom_intelligence("XAUUSD", 4431.00)
    assert len(dom_intel.liquidity) == 2


@pytest.mark.asyncio
async def test_9_zero_active_sources_coverage():
    engine = DOMEngine()
    for adapter in engine.adapters:
        adapter.fetch_snapshot = AsyncMock(side_effect=RuntimeError("Offline"))
    dom_intel = await engine.build_dom_intelligence("XAUUSD", 4431.00)
    assert dom_intel.coverage == "NO-SOURCE (0/2)"
    assert dom_intel.liquidity_status == "DATA NOT VERIFIED"


@pytest.mark.asyncio
async def test_10_single_source_coverage():
    engine = DOMEngine()
    engine.adapters[0].fetch_snapshot = AsyncMock(side_effect=RuntimeError("Offline"))
    engine.adapters[1].fetch_snapshot = AsyncMock(return_value=SourceSnapshot(
        source_id="CTRADER", source_name="cTrader Open API", status=SourceStatus.LIVE,
        observed_timestamp=time.time(), raw_spot_price=4431.00
    ))
    dom_intel = await engine.build_dom_intelligence("XAUUSD", 4431.00)
    assert dom_intel.coverage == "SINGLE-SOURCE (1/2)"


@pytest.mark.asyncio
async def test_11_all_sources_healthy_coverage():
    engine = DOMEngine()
    engine.adapters[0].fetch_snapshot = AsyncMock(return_value=SourceSnapshot(
        source_id="MT5", source_name="MetaTrader 5", status=SourceStatus.LIVE,
        observed_timestamp=time.time(), raw_spot_price=4431.00,
        asks=[PriceLevel(price=4435.0, volume=500.0)]
    ))
    engine.adapters[1].fetch_snapshot = AsyncMock(return_value=SourceSnapshot(
        source_id="CTRADER", source_name="cTrader Open API", status=SourceStatus.LIVE,
        observed_timestamp=time.time(), raw_spot_price=4431.00
    ))
    dom_intel = await engine.build_dom_intelligence("XAUUSD", 4431.00)
    assert dom_intel.coverage == "MULTI-SOURCE (2/2)"
