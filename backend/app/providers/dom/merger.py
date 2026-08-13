from typing import Dict, List, Any, Optional
from app.providers.dom.models import SourceSnapshot, LiquidityZone
from app.providers.dom.normalizer import normalize_futures_price, score_relative_depth

class DOMMerger:
    def merge_dom_sources(
        self,
        active_snapshots: List[SourceSnapshot],
        weights: Dict[str, float],
        basis_value: Optional[float],
        current_price: float,
        step: float = 2.0
    ) -> List[LiquidityZone]:
        """
        Merges normalized DOM liquidity across active sources on the spot price axis.
        """
        ask_buckets: Dict[str, float] = {}
        bid_buckets: Dict[str, float] = {}
        contributing_sources: Dict[str, List[str]] = {}

        p = float(current_price)
        dec = 2 if p >= 5.0 else 4
        fmt = f"{{:.{dec}f}}"

        for snap in active_snapshots:
            w = weights.get(snap.source_id, 0.0)

            # Process Asks
            scored_asks = score_relative_depth(snap.asks)
            for lvl in scored_asks:
                norm_price = normalize_futures_price(lvl.price, basis_value if snap.source_id == "COMEX" else None)
                low_b = round(norm_price / step) * step
                bucket_key = f"{fmt.format(low_b)}–{fmt.format(low_b + step)}"
                
                ask_buckets[bucket_key] = ask_buckets.get(bucket_key, 0.0) + (lvl.relative_score or 0.0) * w
                if bucket_key not in contributing_sources:
                    contributing_sources[bucket_key] = []
                if snap.source_name not in contributing_sources[bucket_key]:
                    contributing_sources[bucket_key].append(snap.source_name)

            # Process Bids
            scored_bids = score_relative_depth(snap.bids)
            for lvl in scored_bids:
                norm_price = normalize_futures_price(lvl.price, basis_value if snap.source_id == "COMEX" else None)
                low_b = round(norm_price / step) * step
                bucket_key = f"{fmt.format(low_b - step)}–{fmt.format(low_b)}"
                
                bid_buckets[bucket_key] = bid_buckets.get(bucket_key, 0.0) + (lvl.relative_score or 0.0) * w
                if bucket_key not in contributing_sources:
                    contributing_sources[bucket_key] = []
                if snap.source_name not in contributing_sources[bucket_key]:
                    contributing_sources[bucket_key].append(snap.source_name)

        zones: List[LiquidityZone] = []

        # Sort ask buckets by depth score descending
        for b_key, b_score in sorted(ask_buckets.items(), key=lambda x: x[1], reverse=True)[:3]:
            impact = "HIGH" if b_score > 40 else ("MODERATE" if b_score > 20 else "LOW")
            zones.append(
                LiquidityZone(
                    price_range=b_key,
                    side="ASK LIQUIDITY",
                    impact=impact,
                    score=round(b_score, 1)
                )
            )

        # Sort bid buckets by depth score descending
        for b_key, b_score in sorted(bid_buckets.items(), key=lambda x: x[1], reverse=True)[:3]:
            impact = "HIGH" if b_score > 40 else ("MODERATE" if b_score > 20 else "LOW")
            zones.append(
                LiquidityZone(
                    price_range=b_key,
                    side="BID LIQUIDITY",
                    impact=impact,
                    score=round(b_score, 1)
                )
            )

        return zones

dom_merger = DOMMerger()
