from typing import Dict, Any, Tuple
from app.models.schemas import DirectionalPressure, TimeframePressure

DEFAULT_WEIGHTS = {
    "momentum": 0.20,
    "structure": 0.20,
    "volume": 0.10,
    "volatility": 0.10,
    "orderflow": 0.15,
    "liquidity": 0.10,
    "session": 0.05,
    "macro": 0.10,
}

class ScoringEngine:
    def __init__(self):
        self.default_weights = dict(DEFAULT_WEIGHTS)

    def calculate_redistributed_weights(self, active_components: Dict[str, bool]) -> Tuple[Dict[str, float], float]:
        """
        Redistributes weights among active components and computes confidence factor.
        """
        active_weight_sum = sum(
            weight for key, weight in self.default_weights.items()
            if active_components.get(key, False)
        )
        
        if active_weight_sum <= 0:
            return {k: 0.0 for k in self.default_weights}, 0.0

        redistributed = {
            key: (weight / active_weight_sum) if active_components.get(key, False) else 0.0
            for key, weight in self.default_weights.items()
        }
        
        # Confidence factor is proportional to available weight fraction
        confidence_factor = active_weight_sum
        return redistributed, confidence_factor

    def compute_timeframe_pressure(
        self,
        symbol: str,
        tf: str,
        raw_indicators: Dict[str, Any]
    ) -> TimeframePressure:
        """
        Calculates buyers and sellers score (0-100) and confidence (0.0-1.0).
        """
        # Extract components or use defaults
        momentum_score = raw_indicators.get("momentum", 50)
        structure_score = raw_indicators.get("structure", 50)
        volume_score = raw_indicators.get("volume", 50)
        orderflow_score = raw_indicators.get("orderflow", 50)

        active = {
            "momentum": "momentum" in raw_indicators,
            "structure": "structure" in raw_indicators,
            "volume": "volume" in raw_indicators,
            "volatility": "volatility" in raw_indicators,
            "orderflow": "orderflow" in raw_indicators,
            "liquidity": "liquidity" in raw_indicators,
            "session": "session" in raw_indicators,
            "macro": "macro" in raw_indicators,
        }

        weights, confidence = self.calculate_redistributed_weights(active)
        
        # Weighted buyer score
        buyer_score = (
            momentum_score * weights["momentum"] +
            structure_score * weights["structure"] +
            volume_score * weights["volume"] +
            orderflow_score * weights["orderflow"] +
            raw_indicators.get("volatility", 50) * weights["volatility"] +
            raw_indicators.get("liquidity", 50) * weights["liquidity"] +
            raw_indicators.get("session", 50) * weights["session"] +
            raw_indicators.get("macro", 50) * weights["macro"]
        )

        buyer_pct = max(0, min(100, int(round(buyer_score))))
        seller_pct = 100 - buyer_pct

        return TimeframePressure(
            buyers=buyer_pct,
            sellers=seller_pct,
            confidence=round(confidence, 2)
        )

    def calculate_overall_bias(
        self,
        directional_pressure: DirectionalPressure
    ) -> Tuple[str, int]:
        tf_weights = {
            "4H": 0.30,
            "1H": 0.25,
            "30M": 0.20,
            "15M": 0.15,
            "5M": 0.10,
        }
        scores = {
            "4H": directional_pressure.tf_4h,
            "1H": directional_pressure.tf_1h,
            "30M": directional_pressure.tf_30m,
            "15M": directional_pressure.tf_15m,
            "5M": directional_pressure.tf_5m,
        }

        # Weight each TF by temporal importance × confidence of its data
        effective_weights = {
            tf: tf_weights[tf] * scores[tf].confidence
            for tf in tf_weights
        }
        total_effective = sum(effective_weights.values())

        if total_effective == 0:
            return "NEUTRAL", 50

        weighted_buyer_total = sum(
            scores[tf].buyers * (effective_weights[tf] / total_effective)
            for tf in tf_weights
        )

        buyer_pct = int(round(weighted_buyer_total))
        seller_pct = 100 - buyer_pct

        # 55% threshold — avoids calling 51/49 a strong BUY signal
        if buyer_pct >= 55:
            return "BUY", buyer_pct
        elif seller_pct >= 55:
            return "SELL", seller_pct
        else:
            return "NEUTRAL", 50

scoring_engine = ScoringEngine()
