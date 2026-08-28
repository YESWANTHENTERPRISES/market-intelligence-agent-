from typing import List, Dict, Any
from app.replay.models import ReplayCandle, ReplayConfig, AblationResult
from app.replay.metrics import metrics_calculator


class AblationEngine:
    """
    Ablation Testing Engine.
    Executes historical replay across 5 distinct system configurations:
    - Test A: Price Action only
    - Test B: Price Action + Important Levels
    - Test C: Price Action + Levels + Market Context
    - Test D: Price Action + Levels + Context + DOM
    - Test E: FULL SYSTEM
    
    Compares Win Rate, Expectancy, Profit Factor, Max Drawdown, & Trade Frequency.
    """

    def get_ablation_configs(self, base_config: ReplayConfig) -> List[Dict[str, Any]]:
        return [
            {
                "test_id": "A",
                "test_name": "Price Action Only",
                "description": "Raw candle structure only (no levels, context, or DOM)",
                "config": base_config.model_copy(update={
                    "enable_dom": False, "enable_levels": False, "enable_context": False
                })
            },
            {
                "test_id": "B",
                "test_name": "PA + Important Levels",
                "description": "Price action structure + deterministic key level clusters",
                "config": base_config.model_copy(update={
                    "enable_dom": False, "enable_levels": True, "enable_context": False
                })
            },
            {
                "test_id": "C",
                "test_name": "PA + Levels + Context",
                "description": "Price action + levels + multi-timeframe regime & session context",
                "config": base_config.model_copy(update={
                    "enable_dom": False, "enable_levels": True, "enable_context": True
                })
            },
            {
                "test_id": "D",
                "test_name": "PA + Levels + Context + DOM",
                "description": "Price action + levels + context + depth of market intelligence",
                "config": base_config.model_copy(update={
                    "enable_dom": True, "enable_levels": True, "enable_context": True
                })
            },
            {
                "test_id": "E",
                "test_name": "FULL SYSTEM",
                "description": "Complete production engine with all intelligence modules enabled",
                "config": base_config.model_copy(update={
                    "enable_dom": True, "enable_levels": True, "enable_context": True
                })
            }
        ]

    def build_ablation_result(
        self,
        test_id: str,
        test_name: str,
        description: str,
        trade_outcomes: List[Any],
        base_config: ReplayConfig
    ) -> AblationResult:
        m, _, _ = metrics_calculator.compute_all_metrics([], [], trade_outcomes)
        status = "COMPLETED"
        if test_id in ["D", "E"] and base_config.is_real_data and not base_config.dom_available:
            status = "DOM_ABLATION_UNAVAILABLE"

        return AblationResult(
            test_id=test_id,
            test_name=test_name,
            description=description,
            total_trades=len(trade_outcomes),
            win_rate=m.win_rate,
            profit_factor=m.profit_factor,
            expectancy=m.expectancy,
            max_drawdown_pct=m.max_drawdown_pct,
            realized_rr=m.realized_rr,
            status=status
        )


ablation_engine = AblationEngine()
