import logging
from typing import Dict, Any, List, Optional, Tuple
from app.models.schemas import (
    TradeScenarioResponse, TradeScenarioDetail, ScenarioTriggerLevel,
    ScenarioLiquidityDetail, MarketContext, ImportantLevels, DOMIntelligence
)

logger = logging.getLogger("trade_scenarios")


class TradeScenarioEngine:
    """
    Deterministic Trade Scenario Engine that evaluates market context, DOM intelligence,
    and Important Levels to identify whether a LONG, SHORT, WAIT, or NO-TRADE scenario is forming.
    
    CRITICAL MANDATE:
    - NO trade execution (no BUY/SELL/ENTRY/SL/TP order placement).
    - Intelligence and scenario reasoning only.
    """

    def evaluate_scenarios(
        self,
        symbol: str,
        current_price: float,
        market_context: Optional[MarketContext] = None,
        important_levels: Optional[ImportantLevels] = None,
        dom_intelligence: Optional[DOMIntelligence] = None,
        ohlc_data: Optional[Dict[str, List[Dict[str, Any]]]] = None
    ) -> TradeScenarioResponse:
        """
        Evaluates potential trade scenarios and returns TradeScenarioResponse payload.
        """
        # Data Quality Gate
        if current_price <= 0 or not market_context:
            return TradeScenarioResponse(
                primary_scenario=None,
                secondary_scenario=None,
                overall_action="NO_TRADE",
                reasons=["Invalid canonical price or missing market context"]
            )

        long_scenarios = self._evaluate_long_scenarios(symbol, current_price, market_context, important_levels, dom_intelligence)
        short_scenarios = self._evaluate_short_scenarios(symbol, current_price, market_context, important_levels, dom_intelligence)

        all_scenarios = long_scenarios + short_scenarios
        all_scenarios.sort(key=lambda s: (s.score * 0.7 + s.confidence * 0.3), reverse=True)

        primary = all_scenarios[0] if all_scenarios else None
        secondary = all_scenarios[1] if len(all_scenarios) > 1 else None

        if not primary or primary.score < 50:
            overall_action = "WAIT"
            reasons = ["No high-probability scenario confirmed", "Price location or structure requires confirmation"]
        elif primary.direction == "LONG" and primary.state in ["CONFIRMED", "CONFIRMATION_REQUIRED"]:
            overall_action = "LONG_SCENARIO"
            reasons = primary.evidence
        elif primary.direction == "SHORT" and primary.state in ["CONFIRMED", "CONFIRMATION_REQUIRED"]:
            overall_action = "SHORT_SCENARIO"
            reasons = primary.evidence
        else:
            overall_action = "WAIT"
            reasons = ["Scenario forming, awaiting key structural trigger"]

        return TradeScenarioResponse(
            primary_scenario=primary,
            secondary_scenario=secondary,
            overall_action=overall_action,
            reasons=reasons
        )

    def _evaluate_long_scenarios(
        self,
        symbol: str,
        current_price: float,
        ctx: MarketContext,
        levels: Optional[ImportantLevels],
        dom: Optional[DOMIntelligence]
    ) -> List[TradeScenarioDetail]:
        scenarios = []
        dom_conf = self._get_dom_confluence(dom, "BID")

        # 1. LONG Pullback
        if ctx.market_bias == "BULLISH" or ctx.structure.htf == "BULLISH":
            near_sup = self._get_nearest_level(levels, current_price, "SUPPORT")
            state = "CONFIRMATION_REQUIRED" if near_sup and abs(near_sup.midpoint - current_price) <= 5.0 else "FORMING"
            score = 75 + (10 if dom_conf == "HIGH" else 0)
            conf = 80 if dom else 65

            scenarios.append(TradeScenarioDetail(
                symbol=symbol,
                scenario="LONG_PULLBACK",
                direction="LONG",
                state=state,
                score=score,
                confidence=conf,
                context_bias="BULLISH",
                trigger_level=self._to_trigger(near_sup),
                liquidity=ScenarioLiquidityDetail(type="SELL_SIDE", status="UNSWEPT", strength="HIGH"),
                evidence=["Bullish higher-timeframe structure", "Price approaching key support zone", "Demand liquidity concentration"],
                confirmation_required=["Bullish CHoCH on 5M", "Bullish displacement candle"],
                invalidation_reasons=["Confirmed acceptance below key support", "HTF structure break"]
            ))

        # 2. LONG Reversal (Sell-side sweep + Bullish CHoCH)
        swept_sell_side = self._has_swept_level(levels, "SELL_SIDE_LIQUIDITY")
        if swept_sell_side or ctx.market_state in ["LIQUIDITY_SWEEP", "POST_SWEEP_REACTION"]:
            scenarios.append(TradeScenarioDetail(
                symbol=symbol,
                scenario="LONG_REVERSAL",
                direction="LONG",
                state="CONFIRMED" if swept_sell_side else "CONFIRMATION_REQUIRED",
                score=82,
                confidence=78,
                context_bias=ctx.market_bias,
                trigger_level=self._to_trigger(swept_sell_side),
                liquidity=ScenarioLiquidityDetail(type="SELL_SIDE", status="SWEPT", strength="HIGH"),
                evidence=["Sell-side liquidity sweep confirmed", "Bullish rejection wick at support"],
                confirmation_required=["Bullish FVG creation", "Hold above sweep low"],
                invalidation_reasons=["Break below sweep low"]
            ))

        return scenarios

    def _evaluate_short_scenarios(
        self,
        symbol: str,
        current_price: float,
        ctx: MarketContext,
        levels: Optional[ImportantLevels],
        dom: Optional[DOMIntelligence]
    ) -> List[TradeScenarioDetail]:
        scenarios = []
        dom_conf = self._get_dom_confluence(dom, "ASK")

        # 1. SHORT Pullback
        if ctx.market_bias == "BEARISH" or ctx.structure.htf == "BEARISH":
            near_res = self._get_nearest_level(levels, current_price, "RESISTANCE")
            state = "CONFIRMATION_REQUIRED" if near_res and abs(near_res.midpoint - current_price) <= 5.0 else "FORMING"
            score = 84 + (10 if dom_conf == "HIGH" else 0)
            conf = 82 if dom else 70

            scenarios.append(TradeScenarioDetail(
                symbol=symbol,
                scenario="SHORT_PULLBACK",
                direction="SHORT",
                state=state,
                score=score,
                confidence=conf,
                context_bias="BEARISH",
                trigger_level=self._to_trigger(near_res),
                liquidity=ScenarioLiquidityDetail(type="BUY_SIDE", status="UNSWEPT", strength="HIGH"),
                evidence=["Bearish HTF structure", "Bearish MTF structure", "LTF bullish retracement toward resistance"],
                confirmation_required=["Buy-side liquidity sweep", "Bearish CHoCH", "Bearish displacement"],
                invalidation_reasons=["Confirmed acceptance above resistance", "Bearish structure invalidated"]
            ))

        # 2. SHORT Reversal (Buy-side sweep)
        swept_buy_side = self._has_swept_level(levels, "BUY_SIDE_LIQUIDITY")
        if swept_buy_side:
            scenarios.append(TradeScenarioDetail(
                symbol=symbol,
                scenario="SHORT_REVERSAL",
                direction="SHORT",
                state="CONFIRMED",
                score=85,
                confidence=80,
                context_bias=ctx.market_bias,
                trigger_level=self._to_trigger(swept_buy_side),
                liquidity=ScenarioLiquidityDetail(type="BUY_SIDE", status="SWEPT", strength="HIGH"),
                evidence=["Buy-side liquidity sweep confirmed", "Bearish rejection wick from resistance"],
                confirmation_required=["Bearish FVG creation", "Hold below sweep high"],
                invalidation_reasons=["Break above sweep high"]
            ))

        return scenarios

    def _get_nearest_level(self, levels: Optional[ImportantLevels], price: float, kind: str) -> Optional[Any]:
        if not levels or not levels.levels:
            return None
        if kind == "RESISTANCE":
            res = [l for l in levels.levels if l.midpoint >= price]
            return min(res, key=lambda l: l.midpoint) if res else None
        else:
            sup = [l for l in levels.levels if l.midpoint < price]
            return max(sup, key=lambda l: l.midpoint) if sup else None

    def _has_swept_level(self, levels: Optional[ImportantLevels], classification: str) -> Optional[Any]:
        if not levels or not levels.levels:
            return None
        for l in levels.levels:
            if getattr(l, "status", "") == "SWEPT" or l.classification == classification:
                if getattr(l, "status", "") == "SWEPT":
                    return l
        return None

    def _get_dom_confluence(self, dom: Optional[DOMIntelligence], side: str) -> str:
        if not dom or not hasattr(dom, "sources"):
            return "UNAVAILABLE"
        inc = [s for s in dom.sources if getattr(s, "included_in_aggregation", False)]
        if len(inc) >= 3:
            return "HIGH"
        elif len(inc) >= 2:
            return "MODERATE"
        elif len(inc) == 1:
            return "LOW"
        return "UNAVAILABLE"

    def _to_trigger(self, lvl: Optional[Any]) -> Optional[ScenarioTriggerLevel]:
        if not lvl:
            return None
        return ScenarioTriggerLevel(
            zone=getattr(lvl, "zone", "N/A"),
            midpoint=getattr(lvl, "midpoint", 0.0),
            classification=getattr(lvl, "classification", "N/A"),
            confluence_score=getattr(lvl, "confluence_score", 50),
            actionability=getattr(lvl, "actionability", "IMMEDIATE")
        )


trade_scenario_engine = TradeScenarioEngine()
