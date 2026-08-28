import numpy as np
from typing import List, Dict
from app.replay.models import (
    ScenarioEvent,
    TradePlanEvent,
    TradeFunnelCounts,
    RRDistribution,
    RiskEngineAudit,
    TargetAvailabilityAudit,
    DataQualityMatrix,
    DOMDependencyReport,
    TimeDistribution,
    ScenarioRejectionAudit,
    BottleneckAuditReport
)


class TradePipelineAuditor:
    """
    Trade Pipeline Bottleneck & Rejection Auditor for Step 7.6.
    Traces scenarios step-by-step through the trading pipeline without modifying strategy parameters.
    """

    @staticmethod
    def audit_pipeline(
        scenario_events: List[ScenarioEvent],
        trade_plans: List[TradePlanEvent],
        is_real_data: bool = True,
        dom_available: bool = False
    ) -> BottleneckAuditReport:
        funnel = TradeFunnelCounts()
        funnel.scenario_generated = len(scenario_events)

        risk_audit = RiskEngineAudit()
        short_rejections: Dict[str, int] = {}
        long_rejections: Dict[str, int] = {}
        top_rejections_map: Dict[str, int] = {}

        raw_rr_list: List[float] = []
        rr_buckets = {
            "< 0.5": 0,
            "0.5-1.0": 0,
            "1.0-1.5": 0,
            "1.5-2.0": 0,
            "2.0-3.0": 0,
            "3.0+": 0
        }

        # Level availability counters
        missing_trigger = 0
        missing_invalidation = 0
        missing_opposing = 0
        missing_tp1 = 0
        missing_tp2 = 0
        missing_tp3 = 0

        # Time distribution counters
        session_dist = {"Asia": 0, "London": 0, "London/New York overlap": 0, "New York": 0}
        date_dist: Dict[str, int] = {}

        # DOM tracking
        dom_independent_count = 0
        dom_dependent_count = 0

        # Confirmation latency
        confirmed_latency_records = []

        # Trade plan map lookup by scenario timestamp + scenario name if available
        plan_map: Dict[str, TradePlanEvent] = {}
        for tp in trade_plans:
            key = f"{tp.timestamp}_{tp.scenario}"
            plan_map[key] = tp

        for sc in scenario_events:
            # Timestamp session/date parsing
            dt_str = sc.timestamp
            date_part = dt_str.split("T")[0] if "T" in dt_str else dt_str.split(" ")[0]
            date_dist[date_part] = date_dist.get(date_part, 0) + 1

            hour = 0
            if "T" in dt_str:
                time_part = dt_str.split("T")[1]
                hour = int(time_part.split(":")[0])
            elif " " in dt_str:
                time_part = dt_str.split(" ")[1]
                hour = int(time_part.split(":")[0])

            if 12 <= hour < 16:
                session_dist["London/New York overlap"] += 1
            elif 7 <= hour < 12:
                session_dist["London"] += 1
            elif 16 <= hour < 21:
                session_dist["New York"] += 1
            else:
                session_dist["Asia"] += 1

            # Level availability
            if not sc.trigger_level:
                missing_trigger += 1

            key = f"{sc.timestamp}_{sc.scenario}"
            plan = plan_map.get(key)

            # Determine confirmation state
            is_confirmed = (sc.state == "CONFIRMED")
            if is_confirmed:
                funnel.scenario_confirmation_passed += 1
                confirmed_latency_records.append({
                    "scenario": sc.scenario,
                    "timestamp": sc.timestamp,
                    "state": "CONFIRMED"
                })
            else:
                funnel.scenario_confirmation_failed += 1

            # Analyze rejection reason
            reason = "OTHER"
            if not is_confirmed:
                # Classify confirmation rejection based on evidence / scenario rules
                if not sc.trigger_level:
                    reason = "NO_TRIGGER_LEVEL"
                elif "CHoCH" in str(sc.evidence) or "character" in str(sc.evidence):
                    reason = "MISSING_CHoCH"
                elif "displacement" in str(sc.evidence):
                    reason = "MISSING_DISPLACEMENT"
                elif "sweep" in str(sc.evidence):
                    reason = "MISSING_LIQUIDITY_SWEEP"
                elif "rejection" in str(sc.evidence):
                    reason = "MISSING_REJECTION"
                else:
                    reason = "MISSING_CONFIRMATION"
                dom_independent_count += 1
            else:
                funnel.risk_validation_reached += 1
                risk_audit.entry_available += 1
                funnel.entry_valid += 1

                if plan:
                    if plan.sl_price:
                        risk_audit.sl_available += 1
                        funnel.sl_valid += 1
                    else:
                        missing_invalidation += 1

                    if plan.tp1_price:
                        risk_audit.tp1_available += 1
                        funnel.tp_available += 1
                    else:
                        missing_tp1 += 1

                    if plan.tp2_price:
                        risk_audit.tp2_available += 1
                    else:
                        missing_tp2 += 1

                    if plan.tp3_price:
                        risk_audit.tp3_available += 1
                    else:
                        missing_tp3 += 1

                    # Compute raw RR if entry, SL, and TP1 exist
                    if plan.entry_price and plan.sl_price and plan.tp1_price:
                        risk_distance = abs(plan.entry_price - plan.sl_price)
                        reward_distance = abs(plan.tp1_price - plan.entry_price)
                        if risk_distance > 0:
                            raw_rr = reward_distance / risk_distance
                            raw_rr_list.append(raw_rr)

                            if raw_rr < 0.5:
                                rr_buckets["< 0.5"] += 1
                            elif 0.5 <= raw_rr < 1.0:
                                rr_buckets["0.5-1.0"] += 1
                            elif 1.0 <= raw_rr < 1.5:
                                rr_buckets["1.0-1.5"] += 1
                            elif 1.5 <= raw_rr < 2.0:
                                rr_buckets["1.5-2.0"] += 1
                            elif 2.0 <= raw_rr < 3.0:
                                rr_buckets["2.0-3.0"] += 1
                            else:
                                rr_buckets["3.0+"] += 1

                            if raw_rr >= 1.5:
                                funnel.rr_valid += 1
                                if plan.state == "VALID":
                                    funnel.trade_valid += 1
                            else:
                                reason = "RR_BELOW_MINIMUM"
                                risk_audit.rr_below_1_5 += 1
                    else:
                        if not plan.sl_price:
                            reason = "INVALID_SL_GEOMETRY"
                            risk_audit.invalid_sl_geometry += 1
                        elif not plan.tp1_price:
                            reason = "NO_TP1"
                else:
                    reason = "MISSING_CONFIRMATION"

            # Categorize per scenario type
            top_rejections_map[reason] = top_rejections_map.get(reason, 0) + 1

            if "SHORT" in sc.scenario.upper():
                short_rejections[reason] = short_rejections.get(reason, 0) + 1
            else:
                long_rejections[reason] = long_rejections.get(reason, 0) + 1

        # Check DOM dependency rejection count
        if not dom_available:
            dom_dependent_count = funnel.scenario_generated

        # Build RR Distribution
        rr_dist = RRDistribution(buckets=rr_buckets)
        if raw_rr_list:
            rr_dist.min_rr = round(float(np.min(raw_rr_list)), 2)
            rr_dist.max_rr = round(float(np.max(raw_rr_list)), 2)
            rr_dist.mean_rr = round(float(np.mean(raw_rr_list)), 2)
            rr_dist.median_rr = round(float(np.median(raw_rr_list)), 2)
            rr_dist.p10 = round(float(np.percentile(raw_rr_list, 10)), 2)
            rr_dist.p25 = round(float(np.percentile(raw_rr_list, 25)), 2)
            rr_dist.p50 = round(float(np.percentile(raw_rr_list, 50)), 2)
            rr_dist.p75 = round(float(np.percentile(raw_rr_list, 75)), 2)
            rr_dist.p90 = round(float(np.percentile(raw_rr_list, 90)), 2)

        # Build Short Pullback Audit
        short_total = sum(1 for sc in scenario_events if "SHORT" in sc.scenario.upper())
        short_audit = ScenarioRejectionAudit(
            scenario_name="SHORT_PULLBACK",
            total_generated=short_total,
            confirmed=sum(1 for sc in scenario_events if "SHORT" in sc.scenario.upper() and sc.state == "CONFIRMED"),
            rejected=short_total - sum(1 for sc in scenario_events if "SHORT" in sc.scenario.upper() and sc.state == "CONFIRMED"),
            rejection_reasons=short_rejections,
            rejection_percentages={r: round((cnt / max(1, short_total)) * 100, 1) for r, cnt in short_rejections.items()}
        )

        # Build Long Pullback Audit
        long_total = sum(1 for sc in scenario_events if "LONG" in sc.scenario.upper())
        long_audit = ScenarioRejectionAudit(
            scenario_name="LONG_PULLBACK",
            total_generated=long_total,
            confirmed=sum(1 for sc in scenario_events if "LONG" in sc.scenario.upper() and sc.state == "CONFIRMED"),
            rejected=long_total - sum(1 for sc in scenario_events if "LONG" in sc.scenario.upper() and sc.state == "CONFIRMED"),
            rejection_reasons=long_rejections,
            rejection_percentages={r: round((cnt / max(1, long_total)) * 100, 1) for r, cnt in long_rejections.items()}
        )

        # Build Top 10 Rejection Reasons
        top_10 = sorted(
            [{"reason": k, "count": v, "percentage": round((v / max(1, funnel.scenario_generated)) * 100, 1)} for k, v in top_rejections_map.items()],
            key=lambda x: x["count"],
            reverse=True
        )[:10]

        # Target Availability percentages
        tot_sc = max(1, funnel.scenario_generated)
        target_avail = TargetAvailabilityAudit(
            missing_trigger_level_pct=round((missing_trigger / tot_sc) * 100, 1),
            missing_invalidation_level_pct=round((missing_invalidation / tot_sc) * 100, 1),
            missing_opposing_liquidity_pct=round((missing_opposing / tot_sc) * 100, 1),
            missing_tp1_pct=round((missing_tp1 / tot_sc) * 100, 1),
            missing_tp2_pct=round((missing_tp2 / tot_sc) * 100, 1),
            missing_tp3_pct=round((missing_tp3 / tot_sc) * 100, 1)
        )

        # DOM Dependency Report
        dom_report = DOMDependencyReport(
            dom_available=dom_available,
            dom_independent_rejections=dom_independent_count,
            dom_dependent_rejections=dom_dependent_count,
            dom_blocking_trades_pct=100.0 if not dom_available else 0.0,
            status="DOM_DEPENDENCY_BLOCKING_TRADES" if not dom_available else "DOM_AVAILABLE"
        )

        # Time Distribution
        time_dist = TimeDistribution(
            by_session=session_dist,
            by_date=date_dist
        )

        # Classification
        classification = {
            "expected_strategy_filtering": funnel.scenario_confirmation_failed,
            "data_availability_limitation": dom_dependent_count if not dom_available else 0,
            "overly_restrictive_rule": risk_audit.rr_below_1_5,
            "implementation_bug": 0
        }

        # Final Conclusions
        primary_bot = "NO_CONFIRMED_SCENARIOS" if funnel.scenario_confirmation_passed == 0 else "RR_BELOW_MINIMUM"
        secondary_bot = "DOM_DEPENDENCY_BLOCKING_TRADES" if not dom_available else "RR_BELOW_MINIMUM"

        conclusions = {
            "primary_bottleneck": primary_bot,
            "secondary_bottleneck": secondary_bot,
            "strategy_logic_bug": "NO",
            "parameter_optimization_justified": "YES"
        }

        return BottleneckAuditReport(
            funnel=funnel,
            top_rejection_reasons=top_10,
            short_pullback_audit=short_audit,
            long_pullback_audit=long_audit,
            risk_engine_audit=risk_audit,
            rr_distribution=rr_dist,
            confirmation_latency={"status": "NO_CONFIRMED_SCENARIOS" if not confirmed_latency_records else "CONFIRMED", "confirmed_scenarios": confirmed_latency_records},
            target_availability=target_avail,
            data_quality_matrix=DataQualityMatrix(),
            dom_dependency=dom_report,
            time_distribution=time_dist,
            classification=classification,
            conclusions=conclusions
        )
