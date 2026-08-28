import logging
from typing import Dict, Any, List, Optional, Tuple
from app.models.schemas import (
    MarketContext, MarketRegimeDetail, MultiTimeframeStructure,
    LiquidityContextDetail, LevelContextDetail, PriceLocationDetail,
    SessionContextDetail, ContextQualityDetail, ImportantLevels,
    DOMIntelligence
)
from app.market.structure import market_structure_engine, calculate_atr

logger = logging.getLogger("market_context")


class MarketContextEngine:
    """
    Deterministic Market Context Engine that interprets market structure,
    DOM liquidity, Important Levels, volatility, and session context into an explainable
    MarketContext object without making trade execution decisions (no BUY/SELL/ENTRY/SL/TP).
    """

    def build_market_context(
        self,
        symbol: str,
        current_price: float,
        important_levels: Optional[ImportantLevels] = None,
        dom_intelligence: Optional[DOMIntelligence] = None,
        ohlc_data: Optional[Dict[str, List[Dict[str, Any]]]] = None,
        session_info: Optional[Any] = None,
        atr: Optional[float] = None
    ) -> MarketContext:
        """
        Builds complete MarketContext payload.
        """
        if atr is None or atr <= 0:
            atr = 8.0 if symbol == "XAUUSD" else (current_price * 0.003)

        # 1. Evaluate Multi-Timeframe Structure
        structure_info = self._evaluate_structure(ohlc_data, current_price, atr)

        # 2. Evaluate Liquidity Context & Imbalance
        liquidity_info = self._evaluate_liquidity_context(current_price, important_levels, dom_intelligence)

        # 3. Evaluate Price Location
        price_loc_info = self._evaluate_price_location(current_price, important_levels, atr)

        # 4. Evaluate Level Context
        level_context_info = self._evaluate_level_context(current_price, important_levels, atr)

        # 5. Evaluate Session Context
        session_context_info = self._evaluate_session_context(session_info)

        # 6. Evaluate Market State & Regime
        market_state, market_bias = self._evaluate_market_state_and_bias(
            structure_info, price_loc_info, liquidity_info
        )

        # 7. Evaluate Conflict, Alignment, & Confidence
        quality_info = self._evaluate_conflict_and_confidence(
            structure_info, liquidity_info, dom_intelligence, important_levels
        )

        # 8. Generate Warnings
        warnings = self._generate_warnings(
            quality_info, structure_info, price_loc_info, important_levels, dom_intelligence
        )

        # 9. Build Evidence List & Summary
        evidence = self._compile_evidence(
            structure_info, liquidity_info, price_loc_info, level_context_info, quality_info
        )
        summary = self._generate_summary(
            symbol, current_price, market_bias, market_state, structure_info, level_context_info
        )

        volatility_label = "NORMAL"
        if atr > 15.0:
            volatility_label = "EXTREME"
        elif atr > 10.0:
            volatility_label = "HIGH"
        elif atr < 3.0:
            volatility_label = "LOW"

        regime_detail = MarketRegimeDetail(
            trend=structure_info["dominant"],
            volatility=volatility_label,
            structure=structure_info["regime_structure"],
            liquidity=liquidity_info["concentration"]
        )

        mtf_struct = MultiTimeframeStructure(
            htf=structure_info["htf"],
            mtf=structure_info["mtf"],
            ltf=structure_info["ltf"],
            dominant=structure_info["dominant"]
        )

        return MarketContext(
            symbol=symbol,
            current_price=current_price,
            market_bias=market_bias,
            bias_confidence=quality_info["confidence"],
            market_state=market_state,
            market_regime=regime_detail,
            structure=mtf_struct,
            liquidity=liquidity_info["details"],
            levels=level_context_info,
            price_location=price_loc_info,
            session=session_context_info,
            context=ContextQualityDetail(
                alignment=quality_info["alignment"],
                conflict=quality_info["conflict"],
                confidence=quality_info["confidence"]
            ),
            warnings=warnings,
            evidence=evidence,
            summary=summary
        )

    def _evaluate_structure(
        self,
        ohlc_data: Optional[Dict[str, List[Dict[str, Any]]]],
        current_price: float,
        atr: float
    ) -> Dict[str, Any]:
        """
        Evaluates HTF (1W, 1D, 4H), MTF (1H, 30M), and LTF (15M, 5M) structure.
        """
        if not ohlc_data:
            return {
                "htf": "NEUTRAL",
                "mtf": "NEUTRAL",
                "ltf": "NEUTRAL",
                "raw_ltf": "NEUTRAL",
                "dominant": "NEUTRAL",
                "regime_structure": "RANGING",
                "has_choch": False,
                "has_displacement": False
            }

        def get_tf_bias(candles: List[Dict[str, Any]], tf_name: str) -> str:
            if not candles or len(candles) < 2:
                return "NEUTRAL"
            swings = market_structure_engine.detect_swings(candles, tf_name, atr=atr)
            bias = self._swings_to_bias(swings)
            if bias != "NEUTRAL":
                return bias
            first_c = candles[0]["close"]
            last_c = candles[-1]["close"]
            diff = last_c - first_c
            if diff > (atr * 0.2):
                return "BULLISH"
            elif diff < -(atr * 0.2):
                return "BEARISH"
            return "NEUTRAL"

        htf_candles = ohlc_data.get("4H") or ohlc_data.get("1D") or ohlc_data.get("1W") or []
        htf_bias = get_tf_bias(htf_candles, "4H")

        mtf_candles = ohlc_data.get("1H") or ohlc_data.get("30M") or []
        mtf_bias = get_tf_bias(mtf_candles, "1H")

        ltf_candles = ohlc_data.get("15M") or ohlc_data.get("5M") or []
        raw_ltf_bias = get_tf_bias(ltf_candles, "15M")

        dominant = htf_bias if htf_bias != "NEUTRAL" else (mtf_bias if mtf_bias != "NEUTRAL" else raw_ltf_bias)

        if dominant == "BEARISH" and raw_ltf_bias == "BULLISH":
            ltf = "BULLISH_RETRACEMENT"
        elif dominant == "BULLISH" and raw_ltf_bias == "BEARISH":
            ltf = "BEARISH_RETRACEMENT"
        else:
            ltf = raw_ltf_bias

        if dominant == "BULLISH":
            regime_structure = "TRENDING_BULLISH"
        elif dominant == "BEARISH":
            regime_structure = "TRENDING_BEARISH"
        elif htf_bias != mtf_bias and htf_bias != "NEUTRAL" and mtf_bias != "NEUTRAL":
            regime_structure = "TRANSITION"
        else:
            regime_structure = "RANGING"

        return {
            "htf": htf_bias,
            "mtf": mtf_bias,
            "ltf": ltf,
            "raw_ltf": raw_ltf_bias,
            "dominant": dominant if dominant != "NEUTRAL" else "NEUTRAL",
            "regime_structure": regime_structure,
            "has_choch": False,
            "has_displacement": any(c.get("range", 0) > (atr * 1.5) for c in (ltf_candles[-5:] if ltf_candles else []))
        }


    def _swings_to_bias(self, swings: List[Dict[str, Any]]) -> str:
        if len(swings) < 2:
            return "NEUTRAL"
        last_swing = swings[-1]
        prev_swing = swings[-2]
        if last_swing["type"] == "SWING_HIGH" and prev_swing["type"] == "SWING_HIGH":
            return "BULLISH" if last_swing["price"] > prev_swing["price"] else "BEARISH"
        elif last_swing["type"] == "SWING_LOW" and prev_swing["type"] == "SWING_LOW":
            return "BULLISH" if last_swing["price"] > prev_swing["price"] else "BEARISH"
        elif last_swing["type"] == "SWING_HIGH" and prev_swing["type"] == "SWING_LOW":
            return "BULLISH"
        elif last_swing["type"] == "SWING_LOW" and prev_swing["type"] == "SWING_HIGH":
            return "BEARISH"
        return "NEUTRAL"

    def _evaluate_liquidity_context(
        self,
        current_price: float,
        important_levels: Optional[ImportantLevels],
        dom_intelligence: Optional[DOMIntelligence]
    ) -> Dict[str, Any]:
        """
        Evaluates nearest buy-side/sell-side liquidity pools and concentration.
        """
        buy_sides = []
        sell_sides = []

        if important_levels and important_levels.levels:
            for lvl in important_levels.levels:
                mid = lvl.midpoint
                if lvl.liquidity.type == "BUY_SIDE" or lvl.classification == "BUY_SIDE_LIQUIDITY" or mid >= current_price:
                    buy_sides.append(mid)
                if lvl.liquidity.type == "SELL_SIDE" or lvl.classification == "SELL_SIDE_LIQUIDITY" or mid < current_price:
                    sell_sides.append(mid)

        # Nearest levels above and below
        above_levels = [p for p in buy_sides if p >= current_price]
        below_levels = [p for p in sell_sides if p < current_price]

        nearest_buy = min(above_levels) if above_levels else None
        nearest_sell = max(below_levels) if below_levels else None

        nearest_above = nearest_buy
        nearest_below = nearest_sell

        # Concentration
        count_above = len(above_levels)
        count_below = len(below_levels)

        if count_above > count_below:
            concentration = "DENSE_ABOVE"
        elif count_below > count_above:
            concentration = "DENSE_BELOW"
        else:
            concentration = "BALANCED"

        details = LiquidityContextDetail(
            nearest_buy_side=nearest_buy,
            nearest_sell_side=nearest_sell,
            nearest_above=nearest_above,
            nearest_below=nearest_below,
            concentration=concentration
        )

        return {
            "details": details,
            "concentration": concentration,
            "nearest_buy": nearest_buy,
            "nearest_sell": nearest_sell
        }

    def _evaluate_price_location(
        self,
        current_price: float,
        important_levels: Optional[ImportantLevels],
        atr: float
    ) -> PriceLocationDetail:
        """
        Evaluates current price location relative to support, resistance, and ATR.
        """
        if not important_levels or not important_levels.levels:
            return PriceLocationDetail(state="BETWEEN_LEVELS", distance_atr=0.0)

        supports = [l for l in important_levels.levels if l.midpoint < current_price]
        resistances = [l for l in important_levels.levels if l.midpoint >= current_price]

        near_sup = max(supports, key=lambda l: l.midpoint) if supports else None
        near_res = min(resistances, key=lambda l: l.midpoint) if resistances else None

        dist_sup_atr = abs(current_price - near_sup.midpoint) / max(0.0001, atr) if near_sup else 999.0
        dist_res_atr = abs(near_res.midpoint - current_price) / max(0.0001, atr) if near_res else 999.0

        min_dist_atr = min(dist_sup_atr, dist_res_atr)

        if dist_res_atr <= 0.5:
            state = "AT_RESISTANCE"
        elif dist_sup_atr <= 0.5:
            state = "AT_SUPPORT"
        elif min_dist_atr <= 1.0:
            state = "NEAR_LIQUIDITY"
        elif min_dist_atr > 3.0:
            state = "EXTENDED"
        else:
            state = "BETWEEN_LEVELS"

        return PriceLocationDetail(
            state=state,
            distance_atr=round(min_dist_atr if min_dist_atr < 900 else 0.0, 2)
        )

    def _evaluate_level_context(
        self,
        current_price: float,
        important_levels: Optional[ImportantLevels],
        atr: float
    ) -> LevelContextDetail:
        """
        Extracts nearest support, resistance, actionable level, and highest confluence level.
        """
        if not important_levels or not important_levels.levels:
            return LevelContextDetail()

        supports = [l for l in important_levels.levels if l.midpoint < current_price]
        resistances = [l for l in important_levels.levels if l.midpoint >= current_price]

        nearest_sup = max(supports, key=lambda l: l.midpoint).midpoint if supports else None
        nearest_res = min(resistances, key=lambda l: l.midpoint).midpoint if resistances else None

        actionable = [l for l in important_levels.levels if getattr(l, "actionability", "IMMEDIATE") in ["IMMEDIATE", "NEAR"]]
        nearest_act = min(actionable, key=lambda l: abs(l.midpoint - current_price)).midpoint if actionable else (nearest_res or nearest_sup)

        highest_conf = max(important_levels.levels, key=lambda l: l.confluence_score).midpoint if important_levels.levels else None

        return LevelContextDetail(
            nearest_support=nearest_sup,
            nearest_resistance=nearest_res,
            nearest_actionable=nearest_act,
            highest_confluence=highest_conf
        )

    def _evaluate_session_context(self, session_info: Optional[Any]) -> SessionContextDetail:
        """
        Evaluates active session.
        """
        if not session_info:
            return SessionContextDetail(name="LONDON_NEW_YORK_OVERLAP", status="ACTIVE")

        sess_name = getattr(session_info, "name", "LONDON_NEW_YORK_OVERLAP")
        sess_status = "ACTIVE" if getattr(session_info, "active", True) else "INACTIVE"

        return SessionContextDetail(name=sess_name, status=sess_status)

    def _evaluate_market_state_and_bias(
        self,
        structure_info: Dict[str, Any],
        price_loc: PriceLocationDetail,
        liquidity_info: Dict[str, Any]
    ) -> Tuple[str, str]:
        """
        Determines high-level market state and directional bias based on structural hierarchy.
        """
        dom_bias = structure_info["dominant"]
        ltf_bias = structure_info["ltf"]

        # Market Bias
        if dom_bias in ["BULLISH", "BEARISH"]:
            market_bias = dom_bias
        else:
            market_bias = "NEUTRAL"

        # Market State
        if ltf_bias == "BULLISH_RETRACEMENT" and dom_bias == "BEARISH":
            market_state = "PULLBACK"
        elif ltf_bias == "BEARISH_RETRACEMENT" and dom_bias == "BULLISH":
            market_state = "PULLBACK"
        elif price_loc.state == "AT_RESISTANCE" and dom_bias == "BULLISH":
            market_state = "BREAKOUT"
        elif price_loc.state == "AT_SUPPORT" and dom_bias == "BEARISH":
            market_state = "BREAKDOWN"
        elif structure_info["regime_structure"] in ["RANGING"]:
            market_state = "RANGE"
        else:
            market_state = "TREND_CONTINUATION"

        return market_state, market_bias

    def _evaluate_conflict_and_confidence(
        self,
        structure_info: Dict[str, Any],
        liquidity_info: Dict[str, Any],
        dom_intelligence: Optional[DOMIntelligence],
        important_levels: Optional[ImportantLevels]
    ) -> Dict[str, Any]:
        """
        Computes conflict boolean, alignment classification, and 0-100 confidence score.
        """
        htf = structure_info["htf"]
        mtf = structure_info["mtf"]
        raw_ltf = structure_info.get("raw_ltf", "NEUTRAL")

        # Conflict check
        conflict = False
        if htf != "NEUTRAL" and mtf != "NEUTRAL" and htf != mtf:
            conflict = True
        if htf != "NEUTRAL" and raw_ltf != "NEUTRAL" and htf != raw_ltf:
            conflict = True

        # Alignment classification
        if htf == mtf and mtf == raw_ltf and htf != "NEUTRAL":
            alignment = "ALIGNED"
        elif htf == mtf and htf != "NEUTRAL":
            alignment = "MOSTLY_ALIGNED"
        else:
            alignment = "CONFLICTING"

        # Confidence calculation
        base_confidence = 85
        if conflict:
            base_confidence -= 20
        if alignment == "ALIGNED":
            base_confidence += 10
        elif alignment == "CONFLICTING":
            base_confidence -= 15

        if important_levels and important_levels.data_quality and important_levels.data_quality.level == "LOW":
            base_confidence -= 15

        confidence = max(20, min(95, base_confidence))

        return {
            "conflict": conflict,
            "alignment": alignment,
            "confidence": confidence
        }

    def _generate_warnings(
        self,
        quality_info: Dict[str, Any],
        structure_info: Dict[str, Any],
        price_loc: PriceLocationDetail,
        important_levels: Optional[ImportantLevels],
        dom_intelligence: Optional[DOMIntelligence]
    ) -> List[str]:
        """
        Identifies no-trade context warning conditions.
        """
        warnings = []
        if quality_info["confidence"] < 50:
            warnings.append("LOW_DATA_CONFIDENCE")
        if quality_info["conflict"]:
            warnings.append("CONFLICTING_STRUCTURE")
        if not important_levels or not important_levels.levels:
            warnings.append("NO_NEARBY_LEVELS")
        if structure_info["dominant"] == "NEUTRAL":
            warnings.append("NO_VALID_MARKET_STRUCTURE")
        return warnings

    def _compile_evidence(
        self,
        structure_info: Dict[str, Any],
        liquidity_info: Dict[str, Any],
        price_loc: PriceLocationDetail,
        level_context: LevelContextDetail,
        quality_info: Dict[str, Any]
    ) -> List[str]:
        evidence = []
        if structure_info["htf"] != "NEUTRAL":
            evidence.append(f"{structure_info['htf'].capitalize()} HTF structure")
        if structure_info["mtf"] != "NEUTRAL":
            evidence.append(f"{structure_info['mtf'].capitalize()} MTF structure")
        if "RETRACEMENT" in structure_info["ltf"]:
            evidence.append(f"LTF {structure_info['ltf'].replace('_', ' ').lower()}")
        if level_context.nearest_resistance:
            evidence.append(f"Resistance at {level_context.nearest_resistance:.2f}")
        if level_context.nearest_support:
            evidence.append(f"Support at {level_context.nearest_support:.2f}")
        if liquidity_info["concentration"] != "BALANCED":
            evidence.append(f"Liquidity concentration {liquidity_info['concentration'].replace('_', ' ').lower()}")
        return evidence

    def _generate_summary(
        self,
        symbol: str,
        current_price: float,
        market_bias: str,
        market_state: str,
        structure_info: Dict[str, Any],
        level_context: LevelContextDetail
    ) -> str:
        bias_str = market_bias.lower()
        dom_struct = structure_info["dominant"].lower()
        ltf_struct = structure_info["ltf"].replace("_", " ").lower()

        res_str = f" to resistance at {level_context.nearest_resistance:.2f}" if level_context.nearest_resistance else ""
        sup_str = f" and support at {level_context.nearest_support:.2f}" if level_context.nearest_support else ""

        return (
            f"{bias_str.capitalize()} higher-timeframe structure ({dom_struct}) with a lower-timeframe {ltf_struct}"
            f"{res_str}{sup_str}."
        )


market_context_engine = MarketContextEngine()
