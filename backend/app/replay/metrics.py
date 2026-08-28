import math
import statistics
from typing import List, Dict, Any, Tuple
from app.replay.models import (
    ScenarioEvent, TradePlanEvent, TradeOutcome, PerformanceMetrics,
    ScenarioStats, ConfidenceBin
)


class MetricsCalculator:
    """
    Performance Metrics, Scenario-Level Statistics, & Confidence Calibration Calculator.
    Calculates detailed quantitative performance metrics for Historical Replay & Strategy Validation.
    """

    def compute_all_metrics(
        self,
        scenario_events: List[ScenarioEvent],
        trade_plans: List[TradePlanEvent],
        trade_outcomes: List[TradeOutcome],
        initial_balance: float = 10000.0
    ) -> Tuple[PerformanceMetrics, List[ScenarioStats], List[ConfidenceBin]]:
        
        # 1. Performance Metrics
        total_setups = len(scenario_events)
        confirmed_setups = len([s for s in scenario_events if s.state == "CONFIRMED"])
        valid_trades = len([p for p in trade_plans if p.state == "VALID"])
        invalid_trades = len([p for p in trade_plans if p.state == "INVALID"])
        wait_scenarios = len([p for p in trade_plans if p.state == "WAIT"])

        wins = len([t for t in trade_outcomes if t.pnl_r > 0])
        losses = len([t for t in trade_outcomes if t.pnl_r < 0])
        breakeven = len([t for t in trade_outcomes if t.pnl_r == 0])
        total_finished = wins + losses

        win_rate = round((wins / total_finished * 100.0), 2) if total_finished > 0 else 0.0
        loss_rate = round((losses / total_finished * 100.0), 2) if total_finished > 0 else 0.0

        avg_planned_rr = round(sum(t.planned_rr for t in trade_outcomes) / len(trade_outcomes), 2) if trade_outcomes else 0.0
        median_planned_rr = round(statistics.median([t.planned_rr for t in trade_outcomes]), 2) if trade_outcomes else 0.0
        avg_realized_rr = round(sum(t.realized_rr for t in trade_outcomes) / len(trade_outcomes), 2) if trade_outcomes else 0.0

        gross_gains_r = sum(t.pnl_r for t in trade_outcomes if t.pnl_r > 0)
        gross_losses_r = abs(sum(t.pnl_r for t in trade_outcomes if t.pnl_r < 0))

        profit_factor = round(gross_gains_r / gross_losses_r, 2) if gross_losses_r > 0 else (round(gross_gains_r, 2) if gross_gains_r > 0 else 0.0)

        avg_win_r = (gross_gains_r / wins) if wins > 0 else 0.0
        avg_loss_r = (gross_losses_r / losses) if losses > 0 else 0.0
        expectancy = round(((win_rate / 100.0) * avg_win_r) - ((loss_rate / 100.0) * avg_loss_r), 2)

        # Drawdown & Losing Streak Calculation
        peak = initial_balance
        equity = initial_balance
        max_dd_dollars = 0.0
        max_dd_pct = 0.0
        max_dd_r = 0.0
        curr_dd_r = 0.0

        max_losing_streak = 0
        curr_losing_streak = 0

        for t in trade_outcomes:
            equity += t.pnl_dollars
            if equity > peak:
                peak = equity
            dd = peak - equity
            if dd > max_dd_dollars:
                max_dd_dollars = dd
                max_dd_pct = round((dd / peak) * 100.0, 2)

            curr_dd_r = curr_dd_r + (-t.pnl_r if t.pnl_r < 0 else 0.0) - (t.pnl_r if t.pnl_r > 0 else 0.0)
            if curr_dd_r > max_dd_r:
                max_dd_r = round(curr_dd_r, 2)

            if t.pnl_r < 0:
                curr_losing_streak += 1
                if curr_losing_streak > max_losing_streak:
                    max_losing_streak = curr_losing_streak
            else:
                curr_losing_streak = 0

        avg_mae = round(sum(t.mae for t in trade_outcomes) / len(trade_outcomes), 2) if trade_outcomes else 0.0
        avg_mfe = round(sum(t.mfe for t in trade_outcomes) / len(trade_outcomes), 2) if trade_outcomes else 0.0

        # TP Hit Rates
        tp1_hits = len([t for t in trade_outcomes if t.outcome in ["TP1_HIT", "TP2_HIT", "TP3_HIT"]])
        tp2_hits = len([t for t in trade_outcomes if t.outcome in ["TP2_HIT", "TP3_HIT"]])
        tp3_hits = len([t for t in trade_outcomes if t.outcome == "TP3_HIT"])

        tp1_rate = round((tp1_hits / len(trade_outcomes) * 100.0), 2) if trade_outcomes else 0.0
        tp2_rate = round((tp2_hits / len(trade_outcomes) * 100.0), 2) if trade_outcomes else 0.0
        tp3_rate = round((tp3_hits / len(trade_outcomes) * 100.0), 2) if trade_outcomes else 0.0

        tp_trades = [t for t in trade_outcomes if t.outcome in ["TP1_HIT", "TP2_HIT", "TP3_HIT"]]
        sl_trades = [t for t in trade_outcomes if t.outcome == "SL_HIT"]

        avg_time_tp = round(sum(t.duration_minutes for t in tp_trades) / len(tp_trades), 1) if tp_trades else 0.0
        avg_time_sl = round(sum(t.duration_minutes for t in sl_trades) / len(sl_trades), 1) if sl_trades else 0.0

        # Directional Performance
        long_trades = [t for t in trade_outcomes if t.direction == "LONG"]
        short_trades = [t for t in trade_outcomes if t.direction == "SHORT"]

        long_perf = self._compute_sub_performance(long_trades)
        short_perf = self._compute_sub_performance(short_trades)

        # Session Performance
        sessions = {}
        for s_name in ["London", "New York", "Asia", "Overlap/Close"]:
            s_tr = [t for t in trade_outcomes if t.session == s_name]
            sessions[s_name] = self._compute_sub_performance(s_tr)

        # Volatility Performance
        vols = {}
        for v_name in ["HIGH", "NORMAL", "LOW", "EXTREME"]:
            v_tr = [t for t in trade_outcomes if t.volatility == v_name]
            vols[v_name] = self._compute_sub_performance(v_tr)

        metrics = PerformanceMetrics(
            total_setups=total_setups,
            confirmed_setups=confirmed_setups,
            valid_trades=valid_trades,
            invalid_trades=invalid_trades,
            wait_scenarios=wait_scenarios,
            wins=wins,
            losses=losses,
            breakeven=breakeven,
            win_rate=win_rate,
            loss_rate=loss_rate,
            avg_rr=avg_planned_rr,
            median_rr=median_planned_rr,
            realized_rr=avg_realized_rr,
            profit_factor=profit_factor,
            expectancy=expectancy,
            max_drawdown_pct=max_dd_pct,
            max_drawdown_r=max_dd_r,
            max_losing_streak=max_losing_streak,
            avg_mae=avg_mae,
            avg_mfe=avg_mfe,
            tp1_hit_rate=tp1_rate,
            tp2_hit_rate=tp2_rate,
            tp3_hit_rate=tp3_rate,
            avg_time_to_tp_mins=avg_time_tp,
            avg_time_to_sl_mins=avg_time_sl,
            long_performance=long_perf,
            short_performance=short_perf,
            session_performance=sessions,
            volatility_performance=vols
        )

        # 2. Scenario-Level Statistics
        scenario_stats = self._compute_scenario_statistics(scenario_events, trade_outcomes)

        # 3. Confidence Calibration
        calibration_bins = self._compute_confidence_calibration(trade_outcomes)

        return metrics, scenario_stats, calibration_bins

    def determine_baseline_status(self, metrics: PerformanceMetrics) -> str:
        """
        Determines the official baseline status flag: PROFITABLE, UNPROVEN, or NEGATIVE.
        Requires >= 10 valid trades, positive expectancy (>0.05 R), and profit factor > 1.1 to claim PROFITABLE.
        """
        if metrics.valid_trades < 10:
            return "UNPROVEN"
        if metrics.expectancy > 0.05 and metrics.profit_factor > 1.1:
            return "PROFITABLE"
        if metrics.expectancy < 0.0:
            return "NEGATIVE"
        return "UNPROVEN"

    def _compute_sub_performance(self, trades: List[TradeOutcome]) -> Dict[str, Any]:
        if not trades:
            return {"total_trades": 0, "win_rate": 0.0, "profit_factor": 0.0, "expectancy": 0.0}
        w = len([t for t in trades if t.pnl_r > 0])
        l = len([t for t in trades if t.pnl_r < 0])
        tot = w + l
        wr = round((w / tot * 100.0), 2) if tot > 0 else 0.0
        gains = sum(t.pnl_r for t in trades if t.pnl_r > 0)
        losses = abs(sum(t.pnl_r for t in trades if t.pnl_r < 0))
        pf = round(gains / losses, 2) if losses > 0 else (round(gains, 2) if gains > 0 else 0.0)
        avg_w = (gains / w) if w > 0 else 0.0
        avg_l = (losses / l) if l > 0 else 0.0
        exp = round(((wr / 100.0) * avg_w) - (((100.0 - wr) / 100.0) * avg_l), 2)

        return {
            "total_trades": len(trades),
            "wins": w,
            "losses": l,
            "win_rate": wr,
            "profit_factor": pf,
            "expectancy": exp,
            "realized_rr": round(sum(t.realized_rr for t in trades) / len(trades), 2)
        }

    def _compute_scenario_statistics(
        self,
        scenario_events: List[ScenarioEvent],
        trades: List[TradeOutcome]
    ) -> List[ScenarioStats]:
        groups: Dict[str, List[TradeOutcome]] = {}
        for t in trades:
            sc = t.scenario
            if sc not in groups:
                groups[sc] = []
            groups[sc].append(t)

        result: List[ScenarioStats] = []
        if groups:
            for sc, sc_trades in groups.items():
                w = len([t for t in sc_trades if t.pnl_r > 0])
                l = len([t for t in sc_trades if t.pnl_r < 0])
                tot = len(sc_trades)
                wr = round((w / (w + l) * 100.0), 2) if (w + l) > 0 else 0.0
                gains = sum(t.pnl_r for t in sc_trades if t.pnl_r > 0)
                losses = abs(sum(t.pnl_r for t in sc_trades if t.pnl_r < 0))
                pf = round(gains / losses, 2) if losses > 0 else (round(gains, 2) if gains > 0 else 0.0)
                avg_w = (gains / w) if w > 0 else 0.0
                avg_l = (losses / l) if l > 0 else 0.0
                exp = round(((wr / 100.0) * avg_w) - (((100.0 - wr) / 100.0) * avg_l), 2)
                avg_planned = round(sum(t.planned_rr for t in sc_trades) / len(sc_trades), 2)
                avg_realized = round(sum(t.realized_rr for t in sc_trades) / len(sc_trades), 2)

                # Sample size warning status
                if tot < 10:
                    s_status = "INSUFFICIENT_SAMPLE"
                elif tot < 30:
                    s_status = "LOW_SAMPLE"
                else:
                    s_status = "OK"

                result.append(ScenarioStats(
                    scenario=sc,
                    total_trades=tot,
                    wins=w,
                    losses=l,
                    win_rate=wr,
                    profit_factor=pf,
                    expectancy=exp,
                    avg_rr=avg_planned,
                    realized_rr=avg_realized,
                    sample_size=tot,
                    sample_status=s_status
                ))
        else:
            # Group scenario events if no trades executed
            sc_counts: Dict[str, int] = {}
            for s in scenario_events:
                sc_counts[s.scenario] = sc_counts.get(s.scenario, 0) + 1
            for sc, count in sc_counts.items():
                if count < 10:
                    s_status = "INSUFFICIENT_SAMPLE"
                elif count < 30:
                    s_status = "LOW_SAMPLE"
                else:
                    s_status = "OK"

                result.append(ScenarioStats(
                    scenario=sc,
                    total_trades=count,
                    wins=0,
                    losses=0,
                    win_rate=0.0,
                    profit_factor=0.0,
                    expectancy=0.0,
                    avg_rr=0.0,
                    realized_rr=0.0,
                    sample_size=count,
                    sample_status=s_status
                ))

        return sorted(result, key=lambda x: x.total_trades, reverse=True)

    def _compute_confidence_calibration(self, trades: List[TradeOutcome]) -> List[ConfidenceBin]:
        bins_def = [
            ("50-59", 50, 59),
            ("60-69", 60, 69),
            ("70-79", 70, 79),
            ("80-89", 80, 89),
            ("90-100", 90, 100)
        ]

        results: List[ConfidenceBin] = []
        for label, min_c, max_c in bins_def:
            b_trades = [t for t in trades if min_c <= t.confidence <= max_c]
            tot = len(b_trades)
            w = len([t for t in b_trades if t.pnl_r > 0])
            l = len([t for t in b_trades if t.pnl_r < 0])
            actual_wr = round((w / (w + l) * 100.0), 2) if (w + l) > 0 else 0.0
            
            gains = sum(t.pnl_r for t in b_trades if t.pnl_r > 0)
            losses = abs(sum(t.pnl_r for t in b_trades if t.pnl_r < 0))
            avg_w = (gains / w) if w > 0 else 0.0
            avg_l = (losses / l) if l > 0 else 0.0
            exp = round(((actual_wr / 100.0) * avg_w) - (((100.0 - actual_wr) / 100.0) * avg_l), 2)

            pred_mid = (min_c + max_c) / 2.0
            is_calib = abs(actual_wr - pred_mid) <= 15.0 if (w + l) >= 3 else True

            results.append(ConfidenceBin(
                bin_label=label,
                min_conf=min_c,
                max_conf=max_c,
                total_trades=tot,
                wins=w,
                actual_win_rate=actual_wr,
                expectancy=exp,
                is_calibrated=is_calib
            ))

        return results


metrics_calculator = MetricsCalculator()

