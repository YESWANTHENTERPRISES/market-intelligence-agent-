from datetime import datetime
from typing import List, Any, Optional, Tuple
from app.replay.models import ReplayCandle, ReplayConfig, ScenarioEvent, TradePlanEvent
from app.models.schemas import SessionInfo, DOMIntelligence, SourceDetail, LiquidityZone
from app.market.important_levels import important_levels_engine
from app.market.context import market_context_engine
from app.market.scenarios import trade_scenario_engine
from app.market.risk import risk_engine
from app.replay.data_loader import HistoricalDataLoader


def get_session_for_timestamp(ts_str: str) -> SessionInfo:
    try:
        dt = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
        hour = dt.hour
    except Exception:
        hour = 12

    if 22 <= hour or hour < 7:
        return SessionInfo(name="Asia", volatility="LOW", relevance="LOW")
    elif 7 <= hour < 12:
        return SessionInfo(name="London", volatility="HIGH", relevance="HIGH")
    elif 12 <= hour < 17:
        return SessionInfo(name="New York", volatility="HIGH", relevance="HIGH")
    else:
        return SessionInfo(name="Overlap/Close", volatility="MODERATE", relevance="MODERATE")


class PointInTimeEvaluator:
    """
    Point-in-Time Data Isolation Engine for Historical Replay.
    Enforces strict zero lookahead bias: at step i (timestamp T), all calculations
    (Structure, Important Levels, Market Context, Scenario Engine, Risk Engine)
    use strictly candles <= timestamp T.
    """

    async def evaluate_step(
        self,
        symbol: str,
        all_5m_candles: List[ReplayCandle],
        step_index: int,
        config: ReplayConfig
    ) -> Tuple[Optional[ScenarioEvent], Optional[TradePlanEvent], Any, Any, Any]:
        """
        Evaluates step_index T cleanly with no forward candle data leakage.
        Returns (scenario_event, trade_plan_event, market_context, important_levels, trade_validation).
        """
        # Sliced 5M candles up to current step (inclusive)
        sliced_5m = all_5m_candles[: step_index + 1]
        curr_candle = sliced_5m[-1]
        curr_price = curr_candle.close
        ts = curr_candle.timestamp

        # Multi-timeframe aggregated candles sliced strictly at T
        ohlc_data = HistoricalDataLoader.aggregate_timeframes(sliced_5m)

        # Point-in-time Session
        session = get_session_for_timestamp(ts)

        # DOM Intelligence (if enabled in config AND available for real data)
        dom: Optional[DOMIntelligence] = None
        if config.enable_dom and (not config.is_real_data or config.dom_available):
            # Build point-in-time DOM proxy based on current price
            dom = DOMIntelligence(
                coverage="MULTI-SOURCE (Dukascopy + OANDA + Binance)",
                sources=[
                    SourceDetail(name="DUKASCOPY", status="LIVE", freshness="0.5s", included_in_aggregation=True),
                    SourceDetail(name="OANDA", status="LIVE", freshness="0.5s", included_in_aggregation=True),
                    SourceDetail(name="BINANCE", status="LIVE", freshness="0.5s", included_in_aggregation=True),
                ],
                current_price=curr_price,
                liquidity=[
                    LiquidityZone(price_range=f"{curr_price+2.0:.2f}-{curr_price+5.0:.2f}", side="ASK", impact="HIGH", score=85),
                    LiquidityZone(price_range=f"{curr_price-5.0:.2f}-{curr_price-2.0:.2f}", side="BID", impact="HIGH", score=85),
                ],
                liquidity_status="AVAILABLE",
                retail_positioning="SHORT_HEAVY",
                futures_liquidity="HIGH",
                divergence="NONE",
                data_quality="HIGH",
                status="LIVE"
            )

        # 1. Important Levels Engine (if enabled)
        levels = None
        if config.enable_levels:
            levels_res = await important_levels_engine.calculate_important_levels(
                symbol=symbol,
                current_price=curr_price,
                ohlc_data=ohlc_data,
                dom_intelligence_data=dom
            )
            # Reconstruct model if returned dict
            from app.models.schemas import ImportantLevels
            levels = ImportantLevels(
                status=levels_res["status"],
                support=levels_res["support"],
                resistance=levels_res["resistance"],
                liquidity=levels_res["liquidity"],
                levels=levels_res["levels"],
                data_quality=levels_res.get("data_quality")
            )

        # 2. Market Context Engine (if enabled)
        ctx = None
        if config.enable_context:
            ctx = market_context_engine.build_market_context(
                symbol=symbol,
                current_price=curr_price,
                important_levels=levels,
                dom_intelligence=dom,
                ohlc_data=ohlc_data,
                session_info=session
            )

        # 3. Trade Scenario Engine
        scenarios_res = trade_scenario_engine.evaluate_scenarios(
            symbol=symbol,
            current_price=curr_price,
            market_context=ctx,
            important_levels=levels,
            dom_intelligence=dom,
            ohlc_data=ohlc_data
        )

        scenario_event: Optional[ScenarioEvent] = None
        if scenarios_res.primary_scenario:
            ps = scenarios_res.primary_scenario
            trigger_mid = ps.trigger_level.midpoint if ps.trigger_level else None
            scenario_event = ScenarioEvent(
                timestamp=ts,
                symbol=symbol,
                scenario=ps.scenario,
                direction=ps.direction,
                state=ps.state,
                price=curr_price,
                score=ps.score,
                confidence=ps.confidence,
                trigger_level=trigger_mid,
                evidence=ps.evidence
            )

        # 4. Risk Engine Validation
        risk_engine.minimum_rr = config.min_rr
        validation_res = risk_engine.validate_trade_scenario(
            symbol=symbol,
            current_price=curr_price,
            trade_scenario=scenarios_res,
            market_context=ctx,
            important_levels=levels,
            dom_intelligence=dom,
            risk_per_trade_pct=config.risk_per_trade_pct
        )

        trade_plan_event: Optional[TradePlanEvent] = None
        if scenarios_res.primary_scenario and validation_res.state in ["VALID", "INVALID", "MARGINAL"]:
            t_id = f"plan_{ts.replace(':', '').replace('-', '')}_{step_index}"
            entry_p = validation_res.entry.price if validation_res.entry else None
            sl_p = validation_res.stop_loss.price if validation_res.stop_loss else None
            tp1_p = validation_res.targets[0].price if validation_res.targets else None
            tp2_p = validation_res.targets[1].price if len(validation_res.targets) > 1 else None
            tp3_p = validation_res.targets[2].price if len(validation_res.targets) > 2 else None
            rr_val = validation_res.risk_reward.tp1 if validation_res.risk_reward else 0.0
            t_score = validation_res.validation.tradeability_score if validation_res.validation else 0

            trade_plan_event = TradePlanEvent(
                trade_id=t_id,
                timestamp=ts,
                symbol=symbol,
                scenario=scenarios_res.primary_scenario.scenario,
                direction=validation_res.direction,
                state=validation_res.state,
                entry_price=entry_p,
                sl_price=sl_p,
                tp1_price=tp1_p,
                tp2_price=tp2_p,
                tp3_price=tp3_p,
                rr=rr_val,
                tradeability_score=t_score,
                confidence=scenarios_res.primary_scenario.confidence,
                reasons=validation_res.reasons
            )

        return scenario_event, trade_plan_event, ctx, levels, validation_res


point_in_time_evaluator = PointInTimeEvaluator()
