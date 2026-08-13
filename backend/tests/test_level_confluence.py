import pytest
from app.market.important_levels import important_levels_engine
from app.providers.dom.normalizer import calculate_basis, normalize_futures_price, renormalize_weights

def test_7_multiple_timeframe_confluence():
    zone_mtf = {
        "timeframes": ["4H", "1H", "30M", "15M"],
        "evidence": ["4H swing high", "1H swing high", "30M swing high", "15M swing high"]
    }
    score, breakdown = important_levels_engine._calculate_confluence_score(
        zone=zone_mtf, current_price=4431.00, atr=5.0, dom_data=None, interactions={}
    )

    assert breakdown["htf_structure"] == 25
    assert breakdown["mtf_agreement"] == 20
    assert score >= 45

def test_8_dom_confluence():
    from app.providers.dom.models import DOMIntelligenceData, SourceDetail, LiquidityZone
    mock_dom = DOMIntelligenceData(
        coverage="MULTI-SOURCE (3/4)",
        sources=[
            SourceDetail(name="COMEX", status="LIVE", freshness="LIVE", included_in_aggregation=True),
            SourceDetail(name="OANDA", status="LIVE", freshness="LIVE", included_in_aggregation=True),
            SourceDetail(name="DUKASCOPY", status="LIVE", freshness="LIVE", included_in_aggregation=True)
        ],
        current_price=4431.00,
        liquidity=[LiquidityZone(price_range="4438–4440", side="ASK LIQUIDITY", impact="HIGH", score=80.0)],
        liquidity_status="VERIFIED",
        retail_positioning="SHORT",
        futures_liquidity="HIGH",
        futures_sell_wall="HIGH",
        divergence="HIGH",
        basis="+$1.80",
        basis_value=1.80,
        data_quality="HIGH"
    )

    zone_dom = {
        "timeframes": ["1H"],
        "evidence": ["1H swing high", "COMEX ask concentration", "OANDA positioning"]
    }

    score, breakdown = important_levels_engine._calculate_confluence_score(
        zone=zone_dom, current_price=4431.00, atr=5.0, dom_data=mock_dom, interactions={}
    )

    assert breakdown["dom_confluence"] == 15
    assert breakdown["liquidity_evidence"] == 10

def test_9_comex_basis_normalization():
    gc_futures_price = 4433.80
    spot_price = 4432.00

    raw_basis, formatted_basis = calculate_basis(gc_futures_price, spot_price, 100.0, 100.0)
    assert raw_basis == 1.80
    assert formatted_basis == "+$1.80"

    comex_level = 4439.80
    normalized = normalize_futures_price(comex_level, raw_basis)
    assert round(normalized, 2) == 4438.00

def test_11_source_weight_redistribution():
    default_weights = {
        "COMEX": 0.40,
        "OANDA": 0.25,
        "DUKASCOPY": 0.20,
        "FXCM": 0.15
    }
    # FXCM is unavailable
    active_sources = ["COMEX", "OANDA", "DUKASCOPY"]
    redistributed = renormalize_weights(active_sources, default_weights)

    assert "FXCM" not in redistributed
    assert sum(redistributed.values()) == pytest.approx(1.0, abs=0.001)
    assert redistributed["COMEX"] > 0.40
    assert redistributed["OANDA"] > 0.25
    assert redistributed["DUKASCOPY"] > 0.20
