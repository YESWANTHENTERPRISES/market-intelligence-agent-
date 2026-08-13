import pytest
from app.scoring.engine import scoring_engine
from app.models.schemas import DirectionalPressure, TimeframePressure

def test_directional_pressure_calculation():
    raw_5m = {"momentum": 38, "structure": 40, "volume": 35, "orderflow": 37}
    result = scoring_engine.compute_timeframe_pressure("XAUUSD", "5M", raw_5m)
    
    assert isinstance(result, TimeframePressure)
    assert result.buyers + result.sellers == 100
    assert result.sellers > result.buyers  # Sellers 62% in our model
    assert result.confidence > 0.0

def test_weight_redistribution_missing_sources():
    active = {
        "momentum": True,
        "structure": True,
        "volume": False,
        "volatility": False,
        "orderflow": True,
        "liquidity": False,
        "session": False,
        "macro": False,
    }
    weights, confidence = scoring_engine.calculate_redistributed_weights(active)
    
    # Active weights: momentum (0.20) + structure (0.20) + orderflow (0.15) = 0.55
    assert round(sum(weights.values()), 4) == 1.0
    assert weights["volume"] == 0.0
    assert confidence == 0.55

def test_overall_bias_determination():
    tf_item = TimeframePressure(buyers=38, sellers=62, confidence=0.8)
    tf_bull = TimeframePressure(buyers=65, sellers=35, confidence=0.8)

    dir_pressure = DirectionalPressure(
        **{"4H": tf_item, "1H": tf_item, "30M": tf_item, "15M": tf_item, "5M": tf_bull}
    )
    
    bias, conf = scoring_engine.calculate_overall_bias(dir_pressure)
    assert bias == "SELL"
    assert conf > 50
