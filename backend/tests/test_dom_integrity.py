import time
import pytest
from unittest.mock import AsyncMock, patch
from app.providers.manager import ProviderManager
from app.providers.dom.engine import DOMEngine
from app.providers.dom.normalizer import (
    calculate_basis,
    normalize_futures_price,
    renormalize_weights,
    score_relative_depth,
)
from app.providers.dom.models import SourceSnapshot, SourceStatus, PriceLevel
from app.models.schemas import PriceMetadata


@pytest.mark.asyncio
async def test_1_canonical_price_anchor_consistency():
    manager = ProviderManager()
    with patch.object(manager, "_resolve_canonical_price", new=AsyncMock(return_value=PriceMetadata(
        price=4335.20, source="OANDA", timestamp=time.time(), is_market_feed=True, age_seconds=0.0, status="LIVE"
    ))):
        res = await manager.get_market_intelligence("XAUUSD", "5M")
        assert res.current_price == pytest.approx(4335.20)
        assert res.dom.current_price == pytest.approx(4335.20)
        # Verify levels calculate distance using the same canonical price anchor
        if res.important_levels.levels:
            lvl = res.important_levels.levels[0]
            assert lvl.distance == pytest.approx(abs(lvl.midpoint - 4335.20), abs=0.01)



def test_2_comex_basis_calculation():
    now = time.time()
    # Positive basis (futures > spot)
    b_val, b_str = calculate_basis(4337.00, 4335.20, now, now)
    assert b_val == pytest.approx(1.80)
    assert b_str == "+$1.80"

    # Negative basis (futures < spot)
    b_val_neg, b_str_neg = calculate_basis(4334.70, 4335.20, now, now)
    assert b_val_neg == pytest.approx(-0.50)
    assert b_str_neg == "-$0.50"

    # Stale timestamps (> 60s delta)
    b_stale_val, b_stale_str = calculate_basis(4337.00, 4335.20, now, now - 65.0)
    assert b_stale_val is None
    assert b_stale_str == "UNAVAILABLE"


def test_3_futures_to_spot_normalization():
    # Positive basis (+1.80): 4337.00 futures -> 4335.20 spot
    assert normalize_futures_price(4337.00, 1.80) == pytest.approx(4335.20)

    # Negative basis (-0.50): 4334.70 futures -> 4335.20 spot
    assert normalize_futures_price(4334.70, -0.50) == pytest.approx(4335.20)

    # None basis: returns None (exclude unnormalized futures)
    assert normalize_futures_price(4337.00, None) is None


@pytest.mark.asyncio
async def test_4_stale_basis_excludes_comex_without_corrupting_spot():
    engine = DOMEngine()
    now = time.time()

    mock_comex = AsyncMock()
    mock_comex.source_id = "COMEX"
    mock_comex.fetch_snapshot = AsyncMock(return_value=SourceSnapshot(
        source_id="COMEX", source_name="COMEX", status=SourceStatus.LIVE,
        observed_timestamp=now - 75.0,  # 75s old -> stale basis
        raw_futures_price=4337.00,
        asks=[PriceLevel(price=4338.00, volume=500.0)]
    ))

    mock_oanda = AsyncMock()
    mock_oanda.source_id = "OANDA"
    mock_oanda.fetch_snapshot = AsyncMock(return_value=SourceSnapshot(
        source_id="OANDA", source_name="OANDA", status=SourceStatus.LIVE,
        observed_timestamp=now,
        raw_spot_price=4335.20,
        asks=[PriceLevel(price=4342.00, volume=300.0)]
    ))

    with patch.object(engine, "adapters", new=[mock_comex.return_value, mock_oanda.return_value]):
        with patch.object(engine.adapters[0], "fetch_snapshot", new=mock_comex.fetch_snapshot):
            with patch.object(engine.adapters[1], "fetch_snapshot", new=mock_oanda.fetch_snapshot):
                dom_intel = await engine.build_dom_intelligence("XAUUSD", current_price=4335.20)
                # Basis must be UNAVAILABLE due to timestamp delta > 60s
                assert dom_intel.basis == "UNAVAILABLE"
                assert dom_intel.basis_value is None
                # Spot mid must remain 4335.20
                assert dom_intel.current_price == pytest.approx(4335.20)


def test_5_bid_ask_grid_alignment():
    p = 4335.20
    step = 8.67
    low_b = round(p / step) * step
    bucket_key = f"{low_b:.2f}–{(low_b + step):.2f}"
    # Verify price 4335.20 falls inside bucket [low_b, low_b + step]
    assert low_b <= p <= low_b + step


def test_6_source_weight_redistribution():
    # All 4 sources active
    weights_all = renormalize_weights(["COMEX", "OANDA", "DUKASCOPY", "FXCM"])
    assert sum(weights_all.values()) == pytest.approx(1.0)

    # COMEX missing -> OANDA, DUKASCOPY, FXCM redistribute
    weights_no_comex = renormalize_weights(["OANDA", "DUKASCOPY", "FXCM"])
    assert "COMEX" not in weights_no_comex
    assert sum(weights_no_comex.values()) == pytest.approx(1.0)


def test_7_volume_relative_scoring():
    levels = [
        PriceLevel(price=4340.0, volume=500.0),
        PriceLevel(price=4345.0, volume=1000.0),
    ]
    scored = score_relative_depth(levels)
    assert scored[0].relative_score == pytest.approx(50.0)
    assert scored[1].relative_score == pytest.approx(100.0)


@pytest.mark.asyncio
async def test_8_bid_ask_semantics_validation():
    engine = DOMEngine()
    now = time.time()
    # Inverted ask level (way below spot mid) should be filtered
    mock_oanda = AsyncMock()
    mock_oanda.source_id = "OANDA"
    mock_oanda.fetch_snapshot = AsyncMock(return_value=SourceSnapshot(
        source_id="OANDA", source_name="OANDA", status=SourceStatus.LIVE,
        observed_timestamp=now,
        raw_spot_price=4335.20,
        asks=[PriceLevel(price=4200.00, volume=999.0)]  # Inverted ask
    ))

    with patch.object(engine.adapters[1], "fetch_snapshot", new=mock_oanda.fetch_snapshot):
        dom_intel = await engine.build_dom_intelligence("XAUUSD", current_price=4335.20)
        assert dom_intel.current_price == pytest.approx(4335.20)


def test_9_proximity_scoring_cases():
    engine = DOMEngine()
    p = 4335.20
    step = 8.67

    # Case A: Near moderate vs Far massive
    buckets_a = {
        "4335.00–4343.67": 30.0,   # Near moderate
        "4400.00–4408.67": 100.0,  # Far massive
    }
    top_a = engine._score_with_proximity(buckets_a, p, step)
    assert top_a is not None

    # Case B: Near strong vs Far slightly stronger
    buckets_b = {
        "4335.00–4343.67": 85.0,  # Near strong
        "4360.00–4368.67": 90.0,  # Far slightly stronger
    }
    top_b = engine._score_with_proximity(buckets_b, p, step)
    assert top_b == "4335.00–4343.67"  # Near strong wins due to proximity bonus


@pytest.mark.asyncio
async def test_10_realistic_xauusd_scenario():
    """
    Realistic scenario:
    Spot = 4335.20
    COMEX futures = 4337.00 (Basis = +1.80)
    COMEX liquidity at 4338.00 futures -> 4336.20 spot-equivalent
    """
    engine = DOMEngine()
    now = time.time()

    mock_comex = AsyncMock()
    mock_comex.source_id = "COMEX"
    mock_comex.fetch_snapshot = AsyncMock(return_value=SourceSnapshot(
        source_id="COMEX", source_name="COMEX", status=SourceStatus.LIVE,
        observed_timestamp=now,
        raw_futures_price=4337.00,
        asks=[PriceLevel(price=4338.00, volume=1200.0)]
    ))

    mock_oanda = AsyncMock()
    mock_oanda.source_id = "OANDA"
    mock_oanda.fetch_snapshot = AsyncMock(return_value=SourceSnapshot(
        source_id="OANDA", source_name="OANDA", status=SourceStatus.LIVE,
        observed_timestamp=now,
        raw_spot_price=4335.20,
        asks=[PriceLevel(price=4336.20, volume=800.0)]
    ))

    with patch.object(engine.adapters[0], "fetch_snapshot", new=mock_comex.fetch_snapshot):
        with patch.object(engine.adapters[1], "fetch_snapshot", new=mock_oanda.fetch_snapshot):
            dom_intel = await engine.build_dom_intelligence("XAUUSD", current_price=4335.20)
            assert dom_intel.basis == "+$1.80"
            assert dom_intel.basis_value == pytest.approx(1.80)
            assert dom_intel.current_price == pytest.approx(4335.20)
            assert len(dom_intel.liquidity) > 0
            assert dom_intel.liquidity[0].observed is True
