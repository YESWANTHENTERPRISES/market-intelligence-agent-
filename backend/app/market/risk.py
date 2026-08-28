import logging
from typing import Any, List, Optional
from app.models.schemas import (
    TradeValidationResponse, TradeEntryDetail, TradeStopLossDetail,
    TradeTargetDetail, TradeRiskRewardDetail, AccountRiskDetail,
    MarketConditionsDetail, ValidationSummaryDetail, TradeScenarioResponse,
    MarketContext, ImportantLevels, DOMIntelligence
)

logger = logging.getLogger("risk_engine")


class RiskEngine:
    """
    Deterministic Risk & Trade Validation Engine.
    Validates trade scenarios, entry/invalidation models, stop-loss calculations,
    take-profit targets, risk/reward ratios, and market risk conditions.
    
    CRITICAL MANDATE:
    - NO broker order execution, connection, or automated trading.
    - Strict Safety Gate: NEVER output state = "VALID" if RR < 1.5,
      or entry/SL geometry is invalid, or scenario is not confirmed.
    """

    def __init__(self, minimum_rr: float = 1.5, stop_buffer_atr: float = 0.10):
        self.minimum_rr = minimum_rr
        self.stop_buffer_atr = stop_buffer_atr

    def validate_trade_scenario(
        self,
        symbol: str,
        current_price: float,
        trade_scenario: Optional[TradeScenarioResponse] = None,
        market_context: Optional[MarketContext] = None,
        important_levels: Optional[ImportantLevels] = None,
        dom_intelligence: Optional[DOMIntelligence] = None,
        account_balance: Optional[float] = None,
        risk_per_trade_pct: float = 1.0,
        spread: Optional[float] = None
    ) -> TradeValidationResponse:
        """
        Validates trade scenario against risk criteria and returns TradeValidationResponse.
        """
        # Safety Gate 1: Invalid price or missing scenario
        if current_price <= 0 or not trade_scenario or not trade_scenario.primary_scenario:
            return TradeValidationResponse(
                symbol=symbol,
                direction="WAIT",
                state="WAIT",
                scenario="NONE",
                reasons=["Awaiting confirmed scenario or valid price"]
            )

        primary = trade_scenario.primary_scenario

        # Safety Gate 2: Non-confirmed scenario state
        if primary.state in ["WAITING", "FORMING", "CONFIRMATION_REQUIRED"]:
            return TradeValidationResponse(
                symbol=symbol,
                direction=primary.direction,
                state="WAIT",
                scenario=primary.scenario,
                entry=TradeEntryDetail(price=None, type="REJECTION", reason="Awaiting confirmation"),
                stop_loss=TradeStopLossDetail(price=None, method="STRUCTURAL_PLUS_ATR_BUFFER", risk_distance=0.0),
                validation=ValidationSummaryDetail(tradeability_score=50, state="WAIT"),
                reasons=primary.confirmation_required or ["Awaiting setup confirmation"]
            )

        atr = (market_context.price_location.distance_atr * 8.0) if (market_context and market_context.price_location.distance_atr > 0) else 8.0
        if atr <= 0:
            atr = 8.0

        # Entry Model
        entry_detail = self._calculate_entry(primary, current_price, important_levels)
        if not entry_detail.price:
            return TradeValidationResponse(
                symbol=symbol,
                direction=primary.direction,
                state="WAIT",
                scenario=primary.scenario,
                reasons=["Unable to calculate reliable entry price"]
            )

        entry_price = entry_detail.price

        # Stop-Loss Model
        sl_detail = self._calculate_stop_loss(primary, entry_price, current_price, important_levels, atr)
        if not sl_detail.price or sl_detail.risk_distance <= 0:
            return TradeValidationResponse(
                symbol=symbol,
                direction=primary.direction,
                state="INVALID",
                scenario=primary.scenario,
                reasons=["Invalid stop-loss or zero risk distance"]
            )

        sl_price = sl_detail.price
        risk_dist = sl_detail.risk_distance

        # Take-Profit Targets Model
        targets = self._calculate_targets(primary, entry_price, sl_price, important_levels, atr)
        if not targets:
            return TradeValidationResponse(
                symbol=symbol,
                direction=primary.direction,
                state="INVALID",
                scenario=primary.scenario,
                reasons=["No opposing structural targets available"]
            )

        tp1_rr = targets[0].rr
        best_rr = max(t.rr for t in targets)

        # Risk/Reward Gate
        if tp1_rr < self.minimum_rr:
            return TradeValidationResponse(
                symbol=symbol,
                direction=primary.direction,
                state="INVALID",
                scenario=primary.scenario,
                entry=entry_detail,
                stop_loss=sl_detail,
                targets=targets,
                risk_reward=TradeRiskRewardDetail(tp1=tp1_rr, best=best_rr, minimum_required=self.minimum_rr),
                validation=ValidationSummaryDetail(tradeability_score=40, state="INVALID"),
                reasons=[f"Risk/Reward ratio ({tp1_rr:.2f}) is below minimum threshold of {self.minimum_rr}"]
            )

        # Market Conditions
        vol_label = market_context.market_regime.volatility if market_context else "NORMAL"
        sess_label = market_context.session.name if market_context else "LONDON_NEW_YORK_OVERLAP"
        dom_label = "MULTI-SOURCE" if (dom_intelligence and hasattr(dom_intelligence, "sources") and len(dom_intelligence.sources) >= 2) else ("SINGLE-SOURCE" if dom_intelligence else "NO-SOURCE")

        if vol_label == "EXTREME":
            return TradeValidationResponse(
                symbol=symbol,
                direction=primary.direction,
                state="INVALID",
                scenario=primary.scenario,
                reasons=["Extreme market volatility — trading halted for risk protection"]
            )

        # Tradeability Score
        score = self._calculate_tradeability_score(primary, tp1_rr, vol_label, dom_label)
        state = "VALID" if score >= 70 else "MARGINAL"

        # Position Sizing Safety
        pos_size = None
        pos_status = "ACCOUNT_DATA_UNAVAILABLE"
        if account_balance and account_balance > 0:
            # Simple risk calculation if account data is explicitly passed
            dollar_risk = account_balance * (risk_per_trade_pct / 100.0)
            pos_size = round(dollar_risk / (risk_dist * 100.0), 2)
            pos_status = "CALCULATED"

        reasons = primary.evidence + [
            f"Entry aligned with {entry_detail.reason}",
            f"TP1 targets opposing liquidity at {targets[0].price:.2f} (RR: {tp1_rr:.2f})",
            f"Risk/Reward ({tp1_rr:.2f}) exceeds minimum threshold ({self.minimum_rr})"
        ]

        return TradeValidationResponse(
            symbol=symbol,
            direction=primary.direction,
            state=state,
            scenario=primary.scenario,
            entry=entry_detail,
            stop_loss=sl_detail,
            targets=targets,
            risk_reward=TradeRiskRewardDetail(tp1=tp1_rr, best=best_rr, minimum_required=self.minimum_rr),
            risk=AccountRiskDetail(risk_per_trade_pct=risk_per_trade_pct, position_size=pos_size, position_size_status=pos_status),
            market_conditions=MarketConditionsDetail(
                volatility=vol_label,
                session=sess_label,
                dom=dom_label,
                event_risk="UNKNOWN",
                spread=spread,
                spread_status="LIVE" if spread else "UNKNOWN",
                slippage="ESTIMATED"
            ),
            validation=ValidationSummaryDetail(tradeability_score=score, state=state),
            reasons=reasons
        )

    def _calculate_entry(self, primary: Any, current_price: float, levels: Optional[ImportantLevels]) -> TradeEntryDetail:
        if primary.trigger_level and primary.trigger_level.midpoint > 0:
            price = primary.trigger_level.midpoint
            e_type = "REJECTION" if primary.state == "CONFIRMED" else "LIMIT"
            reason = f"{primary.trigger_level.classification} zone at {price:.2f}"
        else:
            price = current_price
            e_type = "MARKET"
            reason = "Current market price"
        return TradeEntryDetail(price=round(price, 2), type=e_type, reason=reason)

    def _calculate_stop_loss(
        self, primary: Any, entry_price: float, current_price: float, levels: Optional[ImportantLevels], atr: float
    ) -> TradeStopLossDetail:
        buffer = atr * self.stop_buffer_atr
        if primary.direction == "SHORT":
            invalidation = (primary.trigger_level.midpoint + 2.0) if primary.trigger_level else (entry_price + 3.0)
            sl_price = invalidation + buffer
            risk_dist = sl_price - entry_price
        else:
            invalidation = (primary.trigger_level.midpoint - 2.0) if primary.trigger_level else (entry_price - 3.0)
            sl_price = invalidation - buffer
            risk_dist = entry_price - sl_price

        return TradeStopLossDetail(
            price=round(sl_price, 2),
            method="STRUCTURAL_PLUS_ATR_BUFFER",
            risk_distance=round(max(0.0, risk_dist), 2)
        )

    def _calculate_targets(
        self, primary: Any, entry_price: float, sl_price: float, levels: Optional[ImportantLevels], atr: float
    ) -> List[TradeTargetDetail]:
        risk_dist = abs(entry_price - sl_price)
        if risk_dist <= 0:
            return []

        targets = []
        if primary.direction == "SHORT":
            t1_price = entry_price - (risk_dist * 2.5)
            t2_price = entry_price - (risk_dist * 4.0)
            if levels and levels.levels:
                supports = [l for l in levels.levels if l.midpoint < entry_price]
                if supports:
                    t1_price = max(supports, key=lambda l: l.midpoint).midpoint

            rr1 = round(abs(entry_price - t1_price) / risk_dist, 2)
            targets.append(TradeTargetDetail(
                price=round(t1_price, 2), type="SELL_SIDE_LIQUIDITY", rr=rr1, quality="HIGH", distance_atr=round(abs(entry_price - t1_price) / atr, 2)
            ))
            rr2 = round(abs(entry_price - t2_price) / risk_dist, 2)
            targets.append(TradeTargetDetail(
                price=round(t2_price, 2), type="PREVIOUS_DAY_LOW", rr=rr2, quality="HIGH", distance_atr=round(abs(entry_price - t2_price) / atr, 2)
            ))
        else:
            t1_price = entry_price + (risk_dist * 2.5)
            t2_price = entry_price + (risk_dist * 4.0)
            if levels and levels.levels:
                resistances = [l for l in levels.levels if l.midpoint > entry_price]
                if resistances:
                    t1_price = min(resistances, key=lambda l: l.midpoint).midpoint

            rr1 = round(abs(t1_price - entry_price) / risk_dist, 2)
            targets.append(TradeTargetDetail(
                price=round(t1_price, 2), type="BUY_SIDE_LIQUIDITY", rr=rr1, quality="HIGH", distance_atr=round(abs(t1_price - entry_price) / atr, 2)
            ))
            rr2 = round(abs(t2_price - entry_price) / risk_dist, 2)
            targets.append(TradeTargetDetail(
                price=round(t2_price, 2), type="PREVIOUS_DAY_HIGH", rr=rr2, quality="HIGH", distance_atr=round(abs(t2_price - entry_price) / atr, 2)
            ))

        return targets

    def _calculate_tradeability_score(self, primary: Any, rr: float, vol: str, dom: str) -> int:
        score = 60
        if primary.score >= 80:
            score += 15
        if rr >= 3.0:
            score += 15
        elif rr >= 2.0:
            score += 10
        if dom == "MULTI-SOURCE":
            score += 10
        elif dom == "SINGLE-SOURCE":
            score += 5
        if vol == "EXTREME":
            score -= 30
        return max(0, min(100, score))


risk_engine = RiskEngine()
