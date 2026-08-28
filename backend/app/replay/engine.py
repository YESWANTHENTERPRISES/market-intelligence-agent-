import logging
from typing import List, Optional
from app.replay.models import (
    ReplayCandle, ReplayConfig, ReplayReport, ScenarioEvent, TradePlanEvent, TradeOutcome
)
from app.replay.data_loader import HistoricalDataLoader
from app.replay.point_in_time import point_in_time_evaluator
from app.replay.outcome_engine import forward_outcome_engine
from app.replay.metrics import metrics_calculator
from app.replay.ablation import ablation_engine
from app.replay.walk_forward import walk_forward_engine
from app.replay.monte_carlo import monte_carlo_engine
from app.replay.data_quality import data_quality_auditor
from app.replay.reproducibility import get_reproducibility_metadata

from app.replay.pipeline_auditor import TradePipelineAuditor

logger = logging.getLogger("replay_engine")


class HistoricalReplayEngine:
    """
    STEP 7 & 7.5 & 7.6 — Historical Replay & Strategy Validation Engine Orchestrator.
    Feeds historical candles sequentially with strict point-in-time isolation,
    records scenario events, tracks forward trade outcomes with conservative intrabar resolution,
    computes MAE/MFE, performance metrics, scenario-level statistics, confidence calibration,
    ablation suites, walk-forward partitioning, Monte Carlo simulations, and pipeline bottleneck audit.
    """

    async def run_replay(
        self,
        config: Optional[ReplayConfig] = None,
        custom_candles: Optional[List[ReplayCandle]] = None,
        run_ablation: bool = True,
        run_walk_forward: bool = True,
        run_monte_carlo: bool = True
    ) -> ReplayReport:
        if not config:
            config = ReplayConfig()

        # Load or generate candles
        if custom_candles and len(custom_candles) >= 30:
            candles = custom_candles
            logger.info(f"Replay starting with {len(candles)} custom candles.")
        else:
            candles = HistoricalDataLoader.generate_synthetic_xauusd(num_days=2, start_price=4300.0)
            logger.info(f"Replay generated {len(candles)} synthetic XAUUSD candles.")

        raw_candles_dict = [c.model_dump() if hasattr(c, "model_dump") else c for c in candles]

        # 0. Data Quality Audit
        dq_report = data_quality_auditor.audit_dataset(raw_candles_dict, config.timeframe)
        if dq_report.status == "REJECT" and config.is_real_data:
            raise ValueError(f"Dataset Quality Audit REJECTED: {dq_report.issues}")

        # Reproducibility Hashing
        reprod_meta = get_reproducibility_metadata(raw_candles_dict, config)

        total_candles = len(candles)
        min_warmup = 30  # Need at least 30 5M candles for initial ATR & multi-timeframe structure

        scenario_events: List[ScenarioEvent] = []
        trade_plans: List[TradePlanEvent] = []
        trade_outcomes: List[TradeOutcome] = []

        # Iterate candle by candle sequentially (NO lookahead)
        for i in range(min_warmup, total_candles):
            curr_candle = candles[i]

            # 1. Point-in-time evaluation at timestamp T
            s_evt, t_evt, ctx, levels, val = await point_in_time_evaluator.evaluate_step(
                symbol=config.symbol,
                all_5m_candles=candles,
                step_index=i,
                config=config
            )

            if s_evt:
                scenario_events.append(s_evt)

            if t_evt:
                trade_plans.append(t_evt)

                # If VALID trade plan, track forward outcome on subsequent candles
                if t_evt.state == "VALID":
                    subsequent = candles[i + 1 : i + 1 + config.expiry_candles]

                    sess_name = ctx.session.name if ctx and hasattr(ctx, "session") else "UNKNOWN"
                    vol_name = ctx.market_regime.volatility if ctx and hasattr(ctx, "market_regime") else "NORMAL"

                    outcome = forward_outcome_engine.resolve_trade_outcome(
                        plan=t_evt,
                        subsequent_candles=subsequent,
                        config=config,
                        session_name=sess_name,
                        volatility_label=vol_name
                    )
                    if outcome:
                        trade_outcomes.append(outcome)

        # Compute summary metrics, scenario stats, and confidence calibration
        metrics, sc_stats, calib_bins = metrics_calculator.compute_all_metrics(
            scenario_events=scenario_events,
            trade_plans=trade_plans,
            trade_outcomes=trade_outcomes,
            initial_balance=config.initial_balance
        )

        # Determine Baseline Status
        baseline_status = metrics_calculator.determine_baseline_status(metrics)

        # Step 7.6 Bottleneck & Rejection Audit
        bottleneck_report = TradePipelineAuditor.audit_pipeline(
            scenario_events=scenario_events,
            trade_plans=trade_plans,
            is_real_data=config.is_real_data,
            dom_available=config.dom_available
        )

        # Run Ablation Testing Suite
        ablation_results = []
        if run_ablation:
            for abl_item in ablation_engine.get_ablation_configs(config):
                t_id = abl_item["test_id"]
                t_name = abl_item["test_name"]
                t_desc = abl_item["description"]
                t_cfg = abl_item["config"]

                abl_outcomes = []
                for i in range(min_warmup, total_candles):
                    _, abl_te, abl_ctx, _, _ = await point_in_time_evaluator.evaluate_step(
                        symbol=config.symbol,
                        all_5m_candles=candles,
                        step_index=i,
                        config=t_cfg
                    )
                    if abl_te and abl_te.state == "VALID":
                        sub = candles[i + 1 : i + 1 + t_cfg.expiry_candles]
                        s_n = abl_ctx.session.name if abl_ctx and hasattr(abl_ctx, "session") else "UNKNOWN"
                        v_n = abl_ctx.market_regime.volatility if abl_ctx and hasattr(abl_ctx, "market_regime") else "NORMAL"
                        out = forward_outcome_engine.resolve_trade_outcome(abl_te, sub, t_cfg, s_n, v_n)
                        if out:
                            abl_outcomes.append(out)

                res = ablation_engine.build_ablation_result(t_id, t_name, t_desc, abl_outcomes, config)
                ablation_results.append(res)

        # Run Walk-Forward Validation
        wf_result = None
        if run_walk_forward and len(candles) >= 100:
            tr_c, val_c, oos_c = walk_forward_engine.split_candles(candles)

            tr_dates = (tr_c[0].timestamp, tr_c[-1].timestamp) if tr_c else ("N/A", "N/A")
            val_dates = (val_c[0].timestamp, val_c[-1].timestamp) if val_c else ("N/A", "N/A")
            oos_dates = (oos_c[0].timestamp, oos_c[-1].timestamp) if oos_c else ("N/A", "N/A")

            # Slice outcomes by timestamp
            tr_outcomes = [t for t in trade_outcomes if tr_c[0].timestamp <= t.timestamp <= tr_c[-1].timestamp] if tr_c else []
            val_outcomes = [t for t in trade_outcomes if val_c[0].timestamp <= t.timestamp <= val_c[-1].timestamp] if val_c else []
            oos_outcomes = [t for t in trade_outcomes if oos_c[0].timestamp <= t.timestamp <= oos_c[-1].timestamp] if oos_c else []

            wf_result = walk_forward_engine.evaluate_walk_forward_partitions(
                train_outcomes=tr_outcomes,
                val_outcomes=val_outcomes,
                oos_outcomes=oos_outcomes,
                train_dates=tr_dates,
                val_dates=val_dates,
                oos_dates=oos_dates
            )

        # Run Monte Carlo Simulation
        mc_result = None
        if run_monte_carlo:
            mc_result = monte_carlo_engine.run_simulation(
                trade_outcomes=trade_outcomes,
                num_iterations=10000 if config.is_real_data else 2500,
                initial_balance=config.initial_balance,
                risk_per_trade_pct=config.risk_per_trade_pct
            )

        start_ts = candles[0].timestamp if candles else ""
        end_ts = candles[-1].timestamp if candles else ""

        dom_stat = "AVAILABLE" if config.dom_available else "UNAVAILABLE"

        return ReplayReport(
            symbol=config.symbol,
            timeframe=config.timeframe,
            start_timestamp=start_ts,
            end_timestamp=end_ts,
            total_candles_processed=total_candles,
            dataset_hash=reprod_meta["dataset_hash"],
            config_hash=reprod_meta["config_hash"],
            code_version=reprod_meta["code_version"],
            engine_version=reprod_meta["engine_version"],
            baseline_status=baseline_status,
            dom_status=dom_stat,
            data_quality_report=dq_report,
            metrics=metrics,
            scenario_statistics=sc_stats,
            confidence_calibration=calib_bins,
            scenario_events=scenario_events,
            trade_plans=trade_plans,
            trade_outcomes=trade_outcomes,
            ablation_results=ablation_results,
            walk_forward_results=wf_result,
            monte_carlo_results=mc_result,
            bottleneck_audit_report=bottleneck_report
        )


historical_replay_engine = HistoricalReplayEngine()
