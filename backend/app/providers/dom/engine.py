import time
import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional
from app.providers.dom.models import (
    DOMIntelligenceData,
    LiquidityZone,
    SourceDetail,
    SourceSnapshot,
    SourceStatus,
)
from app.providers.dom.adapters import COMEXAdapter, OANDAAdapter, DukascopyAdapter
from app.providers.dom.normalizer import (
    calculate_basis,
    classify_freshness,
    normalize_futures_price,
    renormalize_weights,
    score_relative_depth,
)

logger = logging.getLogger("dom_engine")

DEFAULT_SOURCE_WEIGHTS = {
    "COMEX": 0.35,
    "OANDA": 0.35,
    "DUKASCOPY": 0.30,
}

class DOMEngine:
    def __init__(self):
        self.adapters = [
            COMEXAdapter(),
            OANDAAdapter(),
            DukascopyAdapter(),
        ]

    def _score_with_proximity(
        self,
        buckets: Dict[str, float],
        current_price: float,
        step: float,
        proximity_weight: float = 0.3
    ) -> Optional[str]:
        if not buckets:
            return None
        best_key = None
        best_combined = -1.0

        for key, raw_score in buckets.items():
            try:
                parts = key.split("–")
                low = float(parts[0])
                high = float(parts[1])
                mid = (low + high) / 2.0

                dist_steps = abs(mid - current_price) / (step if step > 0 else 1.0)
                proximity_bonus = max(0.0, 1.0 - (dist_steps * 0.1))

                combined = (
                    raw_score * (1.0 - proximity_weight)
                    + (proximity_bonus * 100.0) * proximity_weight
                )

                if combined > best_combined:
                    best_combined = combined
                    best_key = key
            except (ValueError, TypeError, ZeroDivisionError, IndexError):
                continue

        return best_key

    async def build_dom_intelligence(self, symbol: str = "XAUUSD", current_price: float = 4431.00) -> DOMIntelligenceData:
        now = time.time()
        
        # 1. Fetch snapshots from all adapters using live/passed current_price
        snapshots: List[SourceSnapshot] = []
        for adapter in self.adapters:
            try:
                snap = await adapter.fetch_snapshot(symbol, current_price=current_price)
                snapshots.append(snap)
            except Exception as e:
                logger.warning(
                    f"[DOM] {adapter.source_name} adapter failed: "
                    f"{type(e).__name__}: {e}"
                )
                snapshots.append(
                    SourceSnapshot(
                        source_id=adapter.source_id,
                        source_name=adapter.source_name,
                        status=SourceStatus.UNAVAILABLE,
                        observed_timestamp=now,
                        freshness_seconds=0.0,
                        freshness_label="UNAVAILABLE",
                        included_in_aggregation=False
                    )
                )

        # 2. Classify freshness & build source details
        active_snapshots: List[SourceSnapshot] = []
        source_details: List[SourceDetail] = []
        comex_snap: Optional[SourceSnapshot] = None
        spot_snap: Optional[SourceSnapshot] = None

        for snap in snapshots:
            status, fresh_label = classify_freshness(snap, now)
            is_active = status in [SourceStatus.LIVE, SourceStatus.DELAYED]
            snap.included_in_aggregation = is_active
            snap.freshness_label = fresh_label

            source_details.append(
                SourceDetail(
                    name=snap.source_name,
                    status=fresh_label,
                    freshness=fresh_label,
                    included_in_aggregation=is_active
                )
            )

            if is_active:
                active_snapshots.append(snap)

            if snap.source_id == "COMEX":
                comex_snap = snap
            elif snap.source_id in ["OANDA", "DUKASCOPY"] and spot_snap is None and is_active:
                spot_snap = snap

        total_sources = len(self.adapters)
        active_count = len(active_snapshots)
        coverage_str = (
            f"MULTI-SOURCE ({active_count}/{total_sources})"
            if active_count > 1
            else (
                f"SINGLE-SOURCE ({active_count}/{total_sources})"
                if active_count == 1
                else f"NO-SOURCE (0/{total_sources})"
            )
        )

        # 3. Calculate Spot/Futures Basis & Coordinate Normalization
        basis_value: Optional[float] = None
        basis_str: str = "UNAVAILABLE"

        futures_mid = comex_snap.raw_futures_price if comex_snap else None
        futures_ts = comex_snap.observed_timestamp if comex_snap else now

        spot_mid = float(current_price) if (current_price is not None and current_price > 0) else None
        if spot_mid is None and spot_snap is not None and spot_snap.raw_spot_price is not None:
            try:
                candidate_spot = float(spot_snap.raw_spot_price)
                if candidate_spot > 0:
                    spot_mid = candidate_spot
            except (TypeError, ValueError):
                spot_mid = None

        if spot_mid is None or spot_mid <= 0:
            spot_mid = 4431.00
            logger.warning(
                f"[DOM] No valid spot price for {symbol}, using benchmark {spot_mid}"
            )

        spot_ts = spot_snap.observed_timestamp if spot_snap else now

        if futures_mid and spot_mid:
            basis_val, b_str = calculate_basis(futures_mid, spot_mid, futures_ts, spot_ts)
            basis_value = basis_val
            basis_str = b_str

        # 4. Normalize prices & depth scores across sources
        active_ids = [s.source_id for s in active_snapshots]
        weights = renormalize_weights(active_ids, DEFAULT_SOURCE_WEIGHTS)

        # 5. Price bucketing into asset-aware discrete zones scaled to current_price
        p = float(spot_mid)
        if p < 5.0:
            dec = 4
            step = max(0.0020, p * 0.0020)
        elif p < 250.0:
            dec = 2
            step = max(0.40, p * 0.0030)
        elif p > 10000.0:
            dec = 0
            step = max(800.0, p * 0.010)
        else:
            dec = 2
            step = max(4.0, p * 0.002)

        fmt = f"{{:.{dec}f}}"
        default_ask_range = f"{fmt.format(p + 1.2 * step)}–{fmt.format(p + 2.2 * step)}"
        default_bid_range = f"{fmt.format(p - 2.2 * step)}–{fmt.format(p - 1.2 * step)}"

        ask_buckets: Dict[str, float] = {}
        bid_buckets: Dict[str, float] = {}

        for snap in active_snapshots:
            w = weights.get(snap.source_id, 0.0)
            
            # Asks (Supply above or around spot mid)
            scored_asks = score_relative_depth(snap.asks)
            for lvl in scored_asks:
                norm_price = normalize_futures_price(lvl.price, basis_value if snap.source_id == "COMEX" else None)
                if norm_price is None:
                    continue
                # Validate ask semantics: ask price should be >= spot_mid - 2.5 * step
                if norm_price < (p - 2.5 * step):
                    logger.warning(f"[DOM] Filtering inverted ask level {norm_price} for {snap.source_id} (spot_mid={p})")
                    continue
                low_b = round(norm_price / step) * step
                bucket_key = f"{fmt.format(low_b)}–{fmt.format(low_b + step)}"
                ask_buckets[bucket_key] = ask_buckets.get(bucket_key, 0.0) + (lvl.relative_score or 0.0) * w

            # Bids (Demand below or around spot mid)
            scored_bids = score_relative_depth(snap.bids)
            for lvl in scored_bids:
                norm_price = normalize_futures_price(lvl.price, basis_value if snap.source_id == "COMEX" else None)
                if norm_price is None:
                    continue
                # Validate bid semantics: bid price should be <= spot_mid + 2.5 * step
                if norm_price > (p + 2.5 * step):
                    logger.warning(f"[DOM] Filtering inverted bid level {norm_price} for {snap.source_id} (spot_mid={p})")
                    continue
                low_b = round(norm_price / step) * step
                bucket_key = f"{fmt.format(low_b)}–{fmt.format(low_b + step)}"
                bid_buckets[bucket_key] = bid_buckets.get(bucket_key, 0.0) + (lvl.relative_score or 0.0) * w

        # Build LiquidityZone objects
        liquidity_zones: List[LiquidityZone] = []

        if ask_buckets:
            top_ask_range = self._score_with_proximity(ask_buckets, p, step) or max(ask_buckets, key=ask_buckets.get)
            top_ask_score = ask_buckets[top_ask_range]
            ask_impact = "HIGH" if top_ask_score > 40 else ("MODERATE" if top_ask_score > 20 else "LOW")
            liquidity_zones.append(
                LiquidityZone(
                    price_range=top_ask_range,
                    side="ASK LIQUIDITY",
                    impact=ask_impact,
                    score=round(top_ask_score, 1),
                    observed=True,
                    source="MULTI-SOURCE" if active_count > 1 else "SINGLE-SOURCE"
                )
            )
        else:
            liquidity_zones.append(
                LiquidityZone(
                    price_range=default_ask_range,
                    side="ASK LIQUIDITY",
                    impact="HIGH",
                    score=65.0,
                    observed=False,
                    source="FALLBACK"
                )
            )

        if bid_buckets:
            top_bid_range = self._score_with_proximity(bid_buckets, p, step) or max(bid_buckets, key=bid_buckets.get)
            top_bid_score = bid_buckets[top_bid_range]
            bid_impact = "HIGH" if top_bid_score > 40 else ("MODERATE" if top_bid_score > 20 else "LOW")
            liquidity_zones.append(
                LiquidityZone(
                    price_range=top_bid_range,
                    side="BID LIQUIDITY",
                    impact=bid_impact,
                    score=round(top_bid_score, 1),
                    observed=True,
                    source="MULTI-SOURCE" if active_count > 1 else "SINGLE-SOURCE"
                )
            )
        else:
            liquidity_zones.append(
                LiquidityZone(
                    price_range=default_bid_range,
                    side="BID LIQUIDITY",
                    impact="HIGH",
                    score=55.0,
                    observed=False,
                    source="FALLBACK"
                )
            )

        liquidity_status = "VERIFIED" if active_count > 0 else "DATA NOT VERIFIED"


        # 6. Aggregated Retail Positioning
        retail_longs = [s.retail_long_pct for s in active_snapshots if s.retail_long_pct is not None]
        if retail_longs:
            avg_long = sum(retail_longs) / len(retail_longs)
            retail_pos = "LONG" if avg_long >= 55.0 else ("SHORT" if avg_long <= 45.0 else "NEUTRAL")
        else:
            retail_pos = "UNAVAILABLE"

        # 7. Futures Sell Wall (COMEX Ask Depth)
        futures_sell_wall = "HIGH"
        futures_liquidity = "HIGH"
        if comex_snap and comex_snap.asks:
            max_comex_ask = max((lvl.volume for lvl in comex_snap.asks), default=0.0)
            futures_sell_wall = "HIGH" if max_comex_ask > 800 else ("MODERATE" if max_comex_ask > 300 else "LOW")
            futures_liquidity = futures_sell_wall
        elif comex_snap and comex_snap.status == SourceStatus.UNAVAILABLE:
            futures_sell_wall = "UNAVAILABLE"
            futures_liquidity = "UNAVAILABLE"

        # 8. Divergence Calculation (OTC Retail Long vs Futures Sell Wall)
        divergence = (
            "UNAVAILABLE"
            if retail_pos == "UNAVAILABLE" or active_count == 0
            else (
                "HIGH"
                if retail_pos == "LONG" and futures_sell_wall == "HIGH"
                else (
                    "MODERATE"
                    if retail_pos != "NEUTRAL" and futures_sell_wall != "LOW"
                    else "LOW"
                )
            )
        )

        # 9. Data Quality Scoring
        data_quality = "MODERATE"
        if active_count >= 3 and basis_value is not None:
            data_quality = "HIGH"
        elif active_count >= 2:
            data_quality = "MODERATE"
        elif active_count == 1:
            data_quality = "LOW"
        else:
            data_quality = "UNAVAILABLE"

        return DOMIntelligenceData(
            coverage=coverage_str,
            sources=source_details,
            current_price=round(spot_mid, 2),
            liquidity=liquidity_zones,
            liquidity_status=liquidity_status,
            retail_positioning=retail_pos,
            futures_liquidity=futures_liquidity,
            futures_sell_wall=futures_sell_wall,
            divergence=divergence,
            basis=basis_str,
            basis_value=basis_value,
            data_quality=data_quality,
            update_timestamp=datetime.now(timezone.utc).isoformat()
        )

dom_engine = DOMEngine()

