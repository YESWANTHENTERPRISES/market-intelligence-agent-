from typing import List, Dict, Any, Optional
from app.replay.models import ReplayCandle, TradePlanEvent, TradeOutcome, ReplayConfig


class ForwardOutcomeEngine:
    """
    Forward Outcome & MAE/MFE Tracking Engine.
    Simulates subsequent candle progression for every VALID trade plan:
    - Tracks exact price trajectory for Maximum Adverse Excursion (MAE) & Maximum Favorable Excursion (MFE).
    - Detects whether TP1, TP2, TP3, or SL was touched first.
    - Applies conservative intrabar conflict resolution (marks AMBIGUOUS if single candle touches both SL and TP).
    - Calculates realized R-multiples and duration.
    """

    def resolve_trade_outcome(
        self,
        plan: TradePlanEvent,
        subsequent_candles: List[ReplayCandle],
        config: ReplayConfig,
        session_name: str = "UNKNOWN",
        volatility_label: str = "NORMAL"
    ) -> Optional[TradeOutcome]:
        if not plan.entry_price or not plan.sl_price or not plan.tp1_price:
            return None

        entry_p = plan.entry_price
        sl_p = plan.sl_price
        tp1_p = plan.tp1_price
        tp2_p = plan.tp2_price
        tp3_p = plan.tp3_price
        direction = plan.direction
        risk_dist = abs(entry_p - sl_p)

        if risk_dist <= 0:
            return None

        mae_price = 0.0
        mfe_price = 0.0

        outcome_status = "PENDING"
        exit_p = entry_p
        exit_ts = plan.timestamp
        duration_candles = 0

        # Iterate forward candle by candle
        for idx, candle in enumerate(subsequent_candles):
            if idx >= config.expiry_candles:
                outcome_status = "EXPIRED"
                exit_p = candle.close
                exit_ts = candle.timestamp
                duration_candles = idx
                break

            high = candle.high
            low = candle.low
            close = candle.close
            ts = candle.timestamp

            if direction == "LONG":
                # MAE: worst adverse price below entry
                adverse_dist = entry_p - low
                if adverse_dist > mae_price:
                    mae_price = adverse_dist

                # MFE: best favorable price above entry
                favorable_dist = high - entry_p
                if favorable_dist > mfe_price:
                    mfe_price = favorable_dist

                # Intrabar collision check
                touches_sl = low <= sl_p
                touches_tp1 = high >= tp1_p

                if touches_sl and touches_tp1:
                    if config.intrabar_resolution == "CONSERVATIVE":
                        outcome_status = "AMBIGUOUS"
                        exit_p = sl_p
                        exit_ts = ts
                        duration_candles = idx + 1
                        break
                    else:
                        # Assume SL first conservatively
                        outcome_status = "SL_HIT"
                        exit_p = sl_p
                        exit_ts = ts
                        duration_candles = idx + 1
                        break
                elif touches_sl:
                    outcome_status = "SL_HIT"
                    exit_p = sl_p
                    exit_ts = ts
                    duration_candles = idx + 1
                    break
                elif touches_tp1:
                    if tp3_p and high >= tp3_p:
                        outcome_status = "TP3_HIT"
                        exit_p = tp3_p
                    elif tp2_p and high >= tp2_p:
                        outcome_status = "TP2_HIT"
                        exit_p = tp2_p
                    else:
                        outcome_status = "TP1_HIT"
                        exit_p = tp1_p
                    exit_ts = ts
                    duration_candles = idx + 1
                    break

            elif direction == "SHORT":
                # MAE: worst adverse price above entry
                adverse_dist = high - entry_p
                if adverse_dist > mae_price:
                    mae_price = adverse_dist

                # MFE: best favorable price below entry
                favorable_dist = entry_p - low
                if favorable_dist > mfe_price:
                    mfe_price = favorable_dist

                # Intrabar collision check
                touches_sl = high >= sl_p
                touches_tp1 = low <= tp1_p

                if touches_sl and touches_tp1:
                    if config.intrabar_resolution == "CONSERVATIVE":
                        outcome_status = "AMBIGUOUS"
                        exit_p = sl_p
                        exit_ts = ts
                        duration_candles = idx + 1
                        break
                    else:
                        outcome_status = "SL_HIT"
                        exit_p = sl_p
                        exit_ts = ts
                        duration_candles = idx + 1
                        break
                elif touches_sl:
                    outcome_status = "SL_HIT"
                    exit_p = sl_p
                    exit_ts = ts
                    duration_candles = idx + 1
                    break
                elif touches_tp1:
                    if tp3_p and low <= tp3_p:
                        outcome_status = "TP3_HIT"
                        exit_p = tp3_p
                    elif tp2_p and low <= tp2_p:
                        outcome_status = "TP2_HIT"
                        exit_p = tp2_p
                    else:
                        outcome_status = "TP1_HIT"
                        exit_p = tp1_p
                    exit_ts = ts
                    duration_candles = idx + 1
                    break

        if outcome_status == "PENDING":
            outcome_status = "EXPIRED"
            if subsequent_candles:
                exit_p = subsequent_candles[-1].close
                exit_ts = subsequent_candles[-1].timestamp
                duration_candles = len(subsequent_candles)

        # Calculate metrics
        mae_r = round(mae_price / risk_dist, 2)
        mfe_r = round(mfe_price / risk_dist, 2)

        # PnL in R-multiples
        if outcome_status == "SL_HIT":
            pnl_r = -1.0
            realized_rr = -1.0
        elif outcome_status in ["TP1_HIT", "TP2_HIT", "TP3_HIT"]:
            if direction == "LONG":
                realized_rr = round((exit_p - entry_p) / risk_dist, 2)
            else:
                realized_rr = round((entry_p - exit_p) / risk_dist, 2)
            pnl_r = max(0.0, realized_rr)
        elif outcome_status == "AMBIGUOUS":
            pnl_r = 0.0
            realized_rr = 0.0
        else:  # EXPIRED
            if direction == "LONG":
                realized_rr = round((exit_p - entry_p) / risk_dist, 2)
            else:
                realized_rr = round((entry_p - exit_p) / risk_dist, 2)
            pnl_r = realized_rr

        # PnL Dollars assuming 1% risk of account ($100 per trade on $10k account)
        dollar_risk = config.initial_balance * (config.risk_per_trade_pct / 100.0)
        pnl_dollars = round(pnl_r * dollar_risk, 2)
        duration_mins = duration_candles * 5

        return TradeOutcome(
            trade_id=plan.trade_id,
            timestamp=plan.timestamp,
            symbol=plan.symbol,
            scenario=plan.scenario,
            direction=direction,
            entry_price=entry_p,
            sl_price=sl_p,
            tp1_price=tp1_p,
            tp2_price=tp2_p,
            tp3_price=tp3_p,
            planned_rr=plan.rr,
            outcome=outcome_status,
            exit_timestamp=exit_ts,
            exit_price=round(exit_p, 2),
            duration_candles=duration_candles,
            duration_minutes=duration_mins,
            mae=round(mae_price, 2),
            mae_r=mae_r,
            mfe=round(mfe_price, 2),
            mfe_r=mfe_r,
            realized_rr=realized_rr,
            pnl_r=round(pnl_r, 2),
            pnl_dollars=pnl_dollars,
            session=session_name,
            volatility=volatility_label,
            confidence=plan.confidence
        )


forward_outcome_engine = ForwardOutcomeEngine()
