import pytest
from app.market.price_areas import price_area_clusterer

def test_6_atr_based_clustering():
    raw_candidates = [
        {"price": 4438.1, "source": "1H", "timeframe": "1H", "type": "SWING_HIGH", "evidence": ["1H swing high 4438.1"]},
        {"price": 4438.4, "source": "30M", "timeframe": "30M", "type": "SWING_HIGH", "evidence": ["30M swing high 4438.4"]},
        {"price": 4438.8, "source": "15M", "timeframe": "15M", "type": "EQUAL_HIGH", "evidence": ["Equal highs 4438.8"]},
        {"price": 4439.0, "source": "DOM", "timeframe": "REALTIME", "type": "ASK_LIQUIDITY", "evidence": ["DOM ask concentration"]},
        {"price": 4439.3, "source": "5M", "timeframe": "5M", "type": "SWING_HIGH", "evidence": ["5M swing high 4439.3"]},
        
        # Farther candidate that should create a separate second cluster
        {"price": 4420.0, "source": "4H", "timeframe": "4H", "type": "SWING_LOW", "evidence": ["4H swing low 4420.0"]}
    ]

    atr = 10.0  # cluster_distance = 10.0 * 0.15 = 1.50
    clusters = price_area_clusterer.cluster_candidates(
        raw_candidates=raw_candidates,
        current_price=4431.00,
        atr=atr,
        decimal_places=2
    )

    # 4438.1 to 4439.3 span is 1.20, which is <= 1.50 -> must cluster into ONE zone!
    assert len(clusters) == 2
    top_cluster = [c for c in clusters if c["midpoint"] > 4430.0][0]

    assert 4437.0 <= top_cluster["zone_low"] <= 4439.0
    assert 4439.0 <= top_cluster["zone_high"] <= 4440.5
    assert len(top_cluster["evidence"]) >= 3
    assert "1H" in top_cluster["timeframes"]
    assert "30M" in top_cluster["timeframes"]
