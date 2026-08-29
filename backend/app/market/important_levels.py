import logging
from typing import Dict, List, Any, Optional, Tuple
from app.market.structure import market_structure_engine, calculate_atr
from app.market.price_areas import price_area_clusterer
from app.liquidity.radar import liquidity_radar
from app.providers.dom.engine import dom_engine

logger = logging.getLogger("important_levels")

TIMEFRAME_WEIGHTS = {
    "1W": 1.00,
    "1D": 1.00,
    "4H": 1.00,
    "1H": 0.85,
    "30M": 0.70,
    "15M": 0.50,
    "5M": 0.30,
    "SESSION": 0.75,
    "REALTIME": 0.60
}

class ImportantLevelsEngine:
    def __init__(self, max_support_count: int = 3, max_resistance_count: int = 3, max_liquidity_count: int = 3):
        self.max_support_count = max_support_count
        self.max_resistance_count = max_resistance_count
        self.max_liquidity_count = max_liquidity_count

    async def calculate_important_levels(
        self,
        symbol: str = "XAUUSD",
        current_price: float = 4431.00,
        ohlc_data: Optional[Dict[str, List[Dict[str, Any]]]] = None,
        dom_intelligence_data: Optional[Any] = None
    ) -> Dict[str, Any]:
        """
        Main calculation entry point for the Important Levels Engine.
        Executes: DETECT -> VALIDATE -> CLUSTER -> SCORE -> RANK -> CLASSIFY -> FILTER -> DISPLAY
        """
        if current_price is None or current_price <= 0:
            return {
                "status": "INSUFFICIENT_DATA",
                "symbol": symbol,
                "current_price": 0.0,
                "levels": [],
                "support": [],
                "resistance": [],
                "liquidity": [],
                "data_quality": {
                    "level": "INSUFFICIENT",
                    "active_sources": 0,
                    "total_sources": 4,
                    "reason": "Missing current market price"
                }
            }

        # Build mock candles if ohlc_data is missing to allow deterministic market calculation
        using_synthetic_fallback = False
        if not ohlc_data:
            logger.warning(
                f"[{symbol}] No live OHLC data provided — using synthetic fallback candles. "
                f"Level detection accuracy is REDUCED. Feed live OHLC data for production use."
            )
            ohlc_data = self._generate_fallback_ohlc(symbol, current_price)
            using_synthetic_fallback = True

        primary_candles = ohlc_data.get("1H") or ohlc_data.get("5M") or []
        atr = calculate_atr(primary_candles) if primary_candles else max(1.0, current_price * 0.002)

        # Step 1: DETECT raw structural candidate levels across timeframes
        raw_candidates: List[Dict[str, Any]] = []

        for tf in ["4H", "1H", "30M", "15M", "5M"]:
            candles = ohlc_data.get(tf, [])
            if not candles:
                continue

            tf_atr = calculate_atr(candles)

            # Swing Highs and Lows
            swings = market_structure_engine.detect_swings(candles, tf, atr=tf_atr)
            for s in swings:
                raw_candidates.append({
                    "price": s["price"],
                    "source": f"{tf}_STRUCTURE",
                    "timeframe": tf,
                    "type": s["type"],
                    "strength": s["strength"],
                    "timestamp": s["timestamp"],
                    "evidence": [f"{tf} {s['type'].replace('_', ' ').lower()} ({s['price']})"]
                })

            # Equal Highs and Lows
            equal_levels = market_structure_engine.detect_equal_highs_lows(candles, tf, atr=tf_atr)
            for eq in equal_levels:
                raw_candidates.append({
                    "price": eq["price"],
                    "source": f"{tf}_LIQUIDITY",
                    "timeframe": tf,
                    "type": eq["type"],
                    "strength": 0.85,
                    "timestamp": "N/A",
                    "evidence": eq["evidence"]
                })

            # Displacement Origins
            displacements = market_structure_engine.detect_displacements(candles, tf, atr=tf_atr)
            for disp in displacements:
                raw_candidates.append({
                    "price": disp["price"],
                    "source": f"{tf}_DISPLACEMENT",
                    "timeframe": tf,
                    "type": disp["type"],
                    "strength": 0.80,
                    "timestamp": "N/A",
                    "evidence": disp["evidence"]
                })

            # Rejections
            rejections = market_structure_engine.detect_rejections(candles, tf, atr=tf_atr)
            for rej in rejections:
                raw_candidates.append({
                    "price": rej["price"],
                    "source": f"{tf}_REJECTION",
                    "timeframe": tf,
                    "type": rej["type"],
                    "strength": 0.75,
                    "timestamp": "N/A",
                    "evidence": rej["evidence"]
                })

            # FVGs (Fair Value Gaps)
            fvgs = market_structure_engine.detect_fvgs(candles, tf, atr=tf_atr)
            for fvg in fvgs:
                raw_candidates.append({
                    "price": fvg["price"],
                    "source": f"{tf}_FVG",
                    "timeframe": tf,
                    "type": fvg["type"],
                    "classification": fvg["classification"],
                    "strength": 0.85,
                    "timestamp": "N/A",
                    "status": fvg.get("status", "ACTIVE"),
                    "evidence": fvg["evidence"]
                })

            # BOS & CHoCH (Structure Breaks)
            bos_list = market_structure_engine.detect_bos_choch(candles, tf, atr=tf_atr)
            for bos in bos_list:
                raw_candidates.append({
                    "price": bos["price"],
                    "source": f"{tf}_BOS",
                    "timeframe": tf,
                    "type": bos["type"],
                    "classification": bos["classification"],
                    "strength": 0.85,
                    "timestamp": "N/A",
                    "evidence": bos["evidence"]
                })


        # Reference Period Levels (PDH, PDL, PWH, PWL, PSH, PSL)
        period_levels = market_structure_engine.compute_session_and_period_levels(ohlc_data)
        for pl in period_levels:
            raw_candidates.append({
                "price": pl["price"],
                "source": "PERIOD_LEVEL",
                "timeframe": pl["timeframe"],
                "type": pl["type"],
                "strength": 0.90 if "W" in pl["type"] or "D" in pl["type"] else 0.75,
                "timestamp": "PERIOD",
                "evidence": pl["evidence"]
            })

        # Fetch / Integrate DOM Data
        if dom_intelligence_data is None:
            dom_intelligence_data = await dom_engine.build_dom_intelligence(symbol, current_price)

        dom_candidates = liquidity_radar.analyze_liquidity_pools(
            equal_levels=[],
            dom_intelligence=dom_intelligence_data,
            current_price=current_price
        )
        for dc in dom_candidates:
            raw_candidates.append(dc)

        if not raw_candidates:
            return {
                "status": "INSUFFICIENT_DATA",
                "symbol": symbol,
                "current_price": current_price,
                "levels": [],
                "support": [],
                "resistance": [],
                "liquidity": [],
                "data_quality": {
                    "level": "INSUFFICIENT",
                    "active_sources": 0,
                    "total_sources": 4,
                    "reason": "No structural or liquidity candidate levels detected"
                }
            }

        # Step 2: CLUSTER raw level candidates into ATR-relative price zones
        dec_places = 4 if current_price < 5.0 else (2 if current_price < 10000.0 else 1)

        zones = price_area_clusterer.cluster_candidates(
            raw_candidates=raw_candidates,
            current_price=current_price,
            atr=atr,
            decimal_places=dec_places
        )

        # Step 3: SCORE & CLASSIFY every clustered price zone
        evaluated_levels = []
        for zone in zones:
            mid = zone["midpoint"]
            
            # Interaction counting over 1H/15M candles
            interactions = market_structure_engine.count_consolidated_interactions(
                target_price=mid,
                candles=primary_candles,
                tolerance=atr * 0.15
            )

            # Score confluence (0-100)
            score, score_breakdown = self._calculate_confluence_score(
                zone=zone,
                current_price=current_price,
                atr=atr,
                dom_data=dom_intelligence_data,
                interactions=interactions
            )

            # Distance metrics
            dist = abs(mid - current_price)
            dist_atr = round(dist / max(0.0001, atr), 2)

            # Classification & Actionability
            importance = self._classify_importance(score)

            if dist_atr <= 1.0:
                actionability = "IMMEDIATE"
            elif dist_atr <= 2.5:
                actionability = "NEAR"
            else:
                actionability = "DISTANT"

            # Liquidity data payload (evaluated case-insensitively)
            ev_str = " ".join([str(e).lower() for e in zone["evidence"]])
            if any(k in ev_str for k in ["buy_side", "equal high", "equal_high", "ask", "pwh", "pdh"]):
                liq_type = "BUY_SIDE"
                liq_strength = "HIGH" if score >= 70 else "MODERATE"
            elif any(k in ev_str for k in ["sell_side", "equal low", "equal_low", "bid", "pwl", "pdl"]):
                liq_type = "SELL_SIDE"
                liq_strength = "HIGH" if score >= 70 else "MODERATE"
            else:
                liq_type = "BUY_SIDE" if mid >= current_price else "SELL_SIDE"
                liq_strength = "HIGH" if score >= 70 else "MODERATE"

            active_dom_sources = []
            if dom_intelligence_data and hasattr(dom_intelligence_data, "sources"):
                active_dom_sources = [s.name for s in dom_intelligence_data.sources if getattr(s, "included_in_aggregation", False)]

            level_obj = {
                "id": f"lvl_{int(mid)}_{int((abs(mid) % 1) * 100):02d}",
                "zone": zone["zone"],
                "midpoint": mid,
                "classification": zone["classification"],
                "importance": importance,
                "actionability": actionability,
                "confluence_score": score,
                "distance": round(dist, dec_places),
                "distance_atr": dist_atr,
                "timeframes": zone["timeframes"],
                "evidence": zone["evidence"],
                "score_breakdown": score_breakdown,
                "liquidity": {
                    "type": liq_type,
                    "strength": liq_strength
                },
                "dom": {
                    "confluence": "HIGH" if (dom_intelligence_data and getattr(dom_intelligence_data, "divergence", "") == "HIGH") else "MODERATE",
                    "sources": active_dom_sources
                },
                "observed": not using_synthetic_fallback,
                "status": zone.get("status", "ACTIVE")
            }
            evaluated_levels.append(level_obj)


        # Step 4: FILTER (Only display VERY HIGH, HIGH, MODERATE — filter out LOW < 50)
        displayable_levels = [lvl for lvl in evaluated_levels if lvl["importance"] in ["VERY_HIGH", "HIGH", "MODERATE"]]

        # Step 5: RANK & SELECT top Support, Resistance, and Liquidity zones
        displayable_levels.sort(key=lambda x: (x["confluence_score"], -x["distance_atr"]), reverse=True)

        support_levels = [
            lvl for lvl in displayable_levels
            if lvl["classification"] in ["SUPPORT", "BROKEN_RESISTANCE"]
            or (lvl["classification"] not in ["RESISTANCE", "BROKEN_SUPPORT"] and lvl["midpoint"] < current_price)
        ]
        resistance_levels = [
            lvl for lvl in displayable_levels
            if lvl["classification"] in ["RESISTANCE", "BROKEN_SUPPORT"]
            or (lvl["classification"] not in ["SUPPORT", "BROKEN_RESISTANCE"] and lvl["midpoint"] >= current_price)
        ]
        # Prevent a level appearing in both lists
        support_ids = {id(l) for l in support_levels}
        resistance_levels = [l for l in resistance_levels if id(l) not in support_ids]
        liquidity_levels = [lvl for lvl in displayable_levels if lvl["liquidity"]["type"] in ["BUY_SIDE", "SELL_SIDE"]]

        top_support = support_levels[:self.max_support_count]
        top_resistance = resistance_levels[:self.max_resistance_count]
        top_liquidity = liquidity_levels[:self.max_liquidity_count]

        # Extract source details for data quality report
        active_dom_sources = []
        if dom_intelligence_data and hasattr(dom_intelligence_data, "sources"):
            active_dom_sources = [
                s.name for s in dom_intelligence_data.sources
                if getattr(s, "included_in_aggregation", False)
            ]

        active_count = len(active_dom_sources) if active_dom_sources else 0
        source_names = ", ".join(active_dom_sources) if active_dom_sources else "No sources active"

        data_quality_report = {
            "level": getattr(dom_intelligence_data, "data_quality", "MODERATE") if dom_intelligence_data else "MODERATE",
            "active_sources": active_count,
            "total_sources": 4,
            "reason": f"{source_names} available"
        }
        if using_synthetic_fallback:
            data_quality_report["data_source"] = "SYNTHETIC_FALLBACK"
            data_quality_report["level"] = "SYNTHETIC_FALLBACK"
        else:
            data_quality_report["data_source"] = "LIVE_OHLC"

        return {
            "status": "AVAILABLE",
            "symbol": symbol,
            "current_price": current_price,
            "levels": displayable_levels,
            "support": top_support,
            "resistance": top_resistance,
            "liquidity": top_liquidity,
            "data_quality": data_quality_report
        }

    def _calculate_confluence_score(
        self,
        zone: Dict[str, Any],
        current_price: float,
        atr: float,
        dom_data: Any,
        interactions: Dict[str, int]
    ) -> Tuple[int, Dict[str, int]]:
        """
        Calculates a deterministic 0-100 confluence score based on prompt weighting rules:
        - Higher timeframe structure: max 25
        - Multi-timeframe agreement: max 20
        - Previous day/week/session: max 15
        - DOM confluence: max 15
        - Liquidity evidence: max 10
        - Price reaction/rejection: max 10
        - Activity/displacement: max 5
        Total = 100
        """
        score_htf = 0
        score_mtf = 0
        score_period = 0
        score_dom = 0
        score_liq = 0
        score_reaction = 0
        score_displacement = 0

        tfs = zone["timeframes"]
        evidence = zone["evidence"]

        # 1. Higher Timeframe Structure (Max 25)
        if "4H" in tfs or "1D" in tfs or "1W" in tfs:
            score_htf = 25
        elif "1H" in tfs:
            score_htf = 18
        elif "30M" in tfs:
            score_htf = 12
        elif "15M" in tfs:
            score_htf = 8
        elif "5M" in tfs:
            score_htf = 4  # 5M-only receives max 4 pts

        # 2. Multi-Timeframe Agreement (Max 20)
        valid_tfs = [t for t in tfs if t in TIMEFRAME_WEIGHTS]
        if len(valid_tfs) >= 4:
            score_mtf = 20
        elif len(valid_tfs) == 3:
            score_mtf = 16
        elif len(valid_tfs) == 2:
            score_mtf = 10
        else:
            score_mtf = 3

        # 3. Previous Day / Week / Session (Max 15)
        for ev in evidence:
            if "Previous Week" in ev or "PWH" in ev or "PWL" in ev:
                score_period = max(score_period, 15)
            elif "Previous Day" in ev or "PDH" in ev or "PDL" in ev:
                score_period = max(score_period, 12)
            elif "Previous Session" in ev or "PSH" in ev or "PSL" in ev:
                score_period = max(score_period, 8)

        # 4. DOM Confluence (Max 15 - DOM score is 0 if DOM unavailable, NO fake redistribution)
        if dom_data and hasattr(dom_data, "sources"):
            active_dom = [s for s in dom_data.sources if getattr(s, "included_in_aggregation", False)]
            if len(active_dom) >= 3:
                score_dom = 15
            elif len(active_dom) == 2:
                score_dom = 10
            elif len(active_dom) == 1:
                score_dom = 5

        # 5. Liquidity Evidence (Max 10)
        if any("Equal highs" in e or "Equal lows" in e or "BUY_SIDE" in e or "SELL_SIDE" in e or "positioning" in e for e in evidence):
            score_liq = 10
        elif any("concentration" in e for e in evidence):
            score_liq = 6

        # 6. Price Reaction / Rejection (Max 10)
        touches = interactions.get("touches", 0)
        rejections = interactions.get("rejections", 0)
        defenses = interactions.get("defenses", 0)
        score_reaction = min(10, (rejections * 4) + (defenses * 3) + (touches * 1))

        # 7. Activity / Displacement (Max 5)
        if any("displacement" in e.lower() or "DISPLACEMENT" in str(zone.get("types")) for e in evidence):
            score_displacement = 5

        total_score = score_htf + score_mtf + score_period + score_dom + score_liq + score_reaction + score_displacement
        total_score = min(100, max(0, total_score))

        breakdown = {
            "htf_structure": score_htf,
            "mtf_agreement": score_mtf,
            "period_levels": score_period,
            "dom_confluence": score_dom,
            "liquidity_evidence": score_liq,
            "price_reaction": score_reaction,
            "displacement": score_displacement,
            "total": total_score
        }

        return total_score, breakdown

    def _classify_importance(self, score: int) -> str:
        if score >= 80:
            return "VERY_HIGH"
        elif score >= 65:
            return "HIGH"
        elif score >= 50:
            return "MODERATE"
        elif score >= 35:
            return "LOW"
        else:
            return "DO_NOT_DISPLAY"

    def _generate_fallback_ohlc(self, symbol: str, p: float) -> Dict[str, List[Dict[str, Any]]]:
        """
        Generates realistic fallback candles scaled to the validated market price p.
        Used when live OHLC candle feeds are initializing.
        """
        dec = 4 if p < 5.0 else (2 if p < 10000.0 else 1)

        step = max(0.002, p * 0.002)

        data = {}
        for tf in ["4H", "1H", "30M", "15M", "5M"]:
            candles = []
            for i in range(30):
                c_open = p + (i - 15) * (step * 0.1)
                c_high = c_open + (step * 0.8)
                c_low = c_open - (step * 0.8)
                c_close = c_open + (step * 0.2 if i % 2 == 0 else -step * 0.2)
                candles.append({
                    "open": round(c_open, dec),
                    "high": round(c_high, dec),
                    "low": round(c_low, dec),
                    "close": round(c_close, dec),
                    "volume": 1000 + (i * 10),
                    "timestamp": f"t_{i}"
                })
            data[tf] = candles
        return data

important_levels_engine = ImportantLevelsEngine()
