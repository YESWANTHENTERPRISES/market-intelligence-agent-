from typing import Dict, List, Any
from app.providers.dom.models import SourceSnapshot, LiquidityZone

class DOMAggregator:
    def evaluate_dom_confluence(
        self,
        active_snapshots: List[SourceSnapshot],
        merged_zones: List[LiquidityZone]
    ) -> Dict[str, Any]:
        """
        Evaluates multi-source DOM confluence.
        If multiple independent sources show significant liquidity near the same price:
        increase confluence classification (DOM CONFLUENCE = HIGH).
        Also generates data quality assessment details.
        """
        total_sources = 4  # COMEX, OANDA, DUKASCOPY, FXCM
        active_count = len(active_snapshots)
        active_names = [s.source_name for s in active_snapshots]

        if active_count >= 3:
            quality = "HIGH"
        elif active_count == 2:
            quality = "MODERATE"
        elif active_count == 1:
            quality = "LOW"
        else:
            quality = "INSUFFICIENT"

        # Active vs unavailable reasoning
        all_possible = ["COMEX", "OANDA", "Dukascopy", "FXCM"]
        unavailable_names = [n for n in all_possible if not any(n.upper() in s.source_id for s in active_snapshots)]
        
        reason = f"{', '.join(active_names)} available"
        if unavailable_names:
            reason += f"; {', '.join(unavailable_names)} unavailable"

        # Evaluate confluence level
        high_impact_count = sum(1 for z in merged_zones if z.impact == "HIGH")
        if active_count >= 2 and high_impact_count >= 1:
            confluence_str = "HIGH"
        elif active_count >= 1:
            confluence_str = "MODERATE"
        else:
            confluence_str = "NONE"

        return {
            "dom_confluence": confluence_str,
            "data_quality": {
                "level": quality,
                "active_sources": active_count,
                "total_sources": total_sources,
                "reason": reason
            }
        }

dom_aggregator = DOMAggregator()
