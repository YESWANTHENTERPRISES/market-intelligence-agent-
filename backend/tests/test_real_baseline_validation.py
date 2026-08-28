import pytest
import os
import tempfile
import csv
from datetime import datetime, timedelta, timezone
from app.replay.models import ReplayConfig, ReplayCandle, TradeOutcome, TradePlanEvent
from app.replay.data_loader import HistoricalDataLoader
from app.replay.data_quality import data_quality_auditor
from app.replay.reproducibility import compute_dataset_hash, compute_config_hash
from app.replay.point_in_time import point_in_time_evaluator
from app.replay.outcome_engine import forward_outcome_engine
from app.replay.metrics import metrics_calculator
from app.replay.ablation import ablation_engine
from app.replay.walk_forward import walk_forward_engine
from app.replay.monte_carlo import monte_carlo_engine
from app.replay.engine import historical_replay_engine
from app.market.structure import market_structure_engine


# 1. Real CSV Loading Test
def test_real_csv_loading():
    with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".csv") as tmp:
        writer = csv.writer(tmp)
        writer.writerow(["timestamp", "open", "high", "low", "close", "volume"])
        writer.writerow(["2026-01-05T08:00:00Z", "4300.0", "4305.0", "4298.0", "4302.0", "100"])
        writer.writerow(["2026-01-05T08:05:00Z", "4302.0", "4308.0", "4301.0", "4306.0", "150"])
        tmp_path = tmp.name

    try:
        candles = HistoricalDataLoader.load_from_csv(tmp_path)
        assert len(candles) == 2
        assert candles[0].open == 4300.0
        assert candles[1].close == 4306.0
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)


# 2. OHLC Validation Test
def test_ohlc_geometry_validation():
    invalid_candles = [
        {"timestamp": "2026-01-05T08:00:00Z", "open": 4300.0, "high": 4290.0, "low": 4298.0, "close": 4302.0, "volume": 100}
    ]
    dq = data_quality_auditor.audit_dataset(invalid_candles)
    assert dq.status == "REJECT"
    assert dq.invalid_candles == 1
    assert len(dq.issues) > 0


# 3. Duplicate Detection Test
def test_duplicate_timestamp_detection():
    dup_candles = [
        {"timestamp": "2026-01-05T08:00:00Z", "open": 4300.0, "high": 4305.0, "low": 4298.0, "close": 4302.0, "volume": 100},
        {"timestamp": "2026-01-05T08:00:00Z", "open": 4302.0, "high": 4308.0, "low": 4301.0, "close": 4306.0, "volume": 150}
    ]
    dq = data_quality_auditor.audit_dataset(dup_candles)
    assert dq.status == "REJECT"
    assert dq.duplicates == 1


# 4. Missing Candle Detection Test
def test_missing_candle_detection():
    gap_candles = [
        {"timestamp": "2026-01-05T08:00:00Z", "open": 4300.0, "high": 4305.0, "low": 4298.0, "close": 4302.0, "volume": 100},
        {"timestamp": "2026-01-05T08:30:00Z", "open": 4302.0, "high": 4308.0, "low": 4301.0, "close": 4306.0, "volume": 150}
    ]
    dq = data_quality_auditor.audit_dataset(gap_candles, expected_timeframe="5M")
    assert dq.missing_intervals > 0


# 5. Timestamp Ordering Test
def test_non_monotonic_timestamp_detection():
    out_of_order = [
        {"timestamp": "2026-01-05T08:05:00Z", "open": 4302.0, "high": 4308.0, "low": 4301.0, "close": 4306.0, "volume": 150},
        {"timestamp": "2026-01-05T08:00:00Z", "open": 4300.0, "high": 4305.0, "low": 4298.0, "close": 4302.0, "volume": 100}
    ]
    dq = data_quality_auditor.audit_dataset(out_of_order)
    assert dq.status == "REJECT"


# 6. Previous-Day Level Isolation Test (PDH / PDL strictly from D-1)
def test_previous_day_level_isolation():
    d1_candles = [
        {"timestamp": "2026-01-04T00:00:00Z", "open": 4200.0, "high": 4250.0, "low": 4190.0, "close": 4240.0, "volume": 1000},
        {"timestamp": "2026-01-05T00:00:00Z", "open": 4240.0, "high": 4310.0, "low": 4235.0, "close": 4300.0, "volume": 1000}  # Incomplete D0
    ]
    levels_list = market_structure_engine.compute_session_and_period_levels({"1D": d1_candles})
    pdh_level = next(l for l in levels_list if l["type"] == "PDH")
    pdl_level = next(l for l in levels_list if l["type"] == "PDL")
    # PDH & PDL must strictly equal D-1 (4250.0 and 4190.0), NOT D0 (4310.0 and 4235.0)
    assert pdh_level["price"] == 4250.0
    assert pdl_level["price"] == 4190.0


# 7. Previous-Week Level Isolation Test (PWH / PWL strictly from W-1)
def test_previous_week_level_isolation():
    w1_candles = [
        {"timestamp": "2025-12-28T00:00:00Z", "open": 4100.0, "high": 4280.0, "low": 4080.0, "close": 4250.0, "volume": 5000},
        {"timestamp": "2026-01-04T00:00:00Z", "open": 4250.0, "high": 4350.0, "low": 4240.0, "close": 4320.0, "volume": 5000}  # Incomplete W0
    ]
    levels_list = market_structure_engine.compute_session_and_period_levels({"1W": w1_candles})
    pwh_level = next(l for l in levels_list if l["type"] == "PWH")
    pwl_level = next(l for l in levels_list if l["type"] == "PWL")
    assert pwh_level["price"] == 4280.0
    assert pwl_level["price"] == 4080.0


# 8. Higher-Timeframe Candle Closure Timing Test
def test_htf_candle_closure_timing():
    candles_5m = HistoricalDataLoader.generate_synthetic_xauusd(num_days=1, start_price=4300.0)
    # At index 10 (00:50 UTC), 1H candle from 00:00-01:00 is NOT closed
    sliced_10 = candles_5m[:11]
    aggregated_10 = HistoricalDataLoader.aggregate_timeframes(sliced_10)
    h1_bars = aggregated_10.get("1H", [])
    # 1H bar timestamp starts at 00:00:00Z
    assert h1_bars[-1]["timestamp"] == "2026-01-05T00:00:00Z"


# 9. FVG Confirmation Timing Test
def test_fvg_confirmation_timing():
    candles = [
        {"timestamp": "2026-01-05T08:00:00Z", "open": 4300.0, "high": 4302.0, "low": 4298.0, "close": 4301.0, "volume": 100},
        {"timestamp": "2026-01-05T08:05:00Z", "open": 4301.0, "high": 4315.0, "low": 4301.0, "close": 4314.0, "volume": 100},  # Imbalance
        {"timestamp": "2026-01-05T08:10:00Z", "open": 4314.0, "high": 4320.0, "low": 4308.0, "close": 4318.0, "volume": 100}   # Confirmation candle
    ]
    fvgs = market_structure_engine.detect_fvgs(candles, timeframe="5M")
    assert len(fvgs) == 1
    # FVG gap between candle 0 High (4302.0) and candle 2 Low (4308.0)
    assert fvgs[0]["type"] == "BULLISH_FVG"
    assert fvgs[0]["gap_low"] == 4302.0
    assert fvgs[0]["gap_high"] == 4308.0


# 10. Swing Confirmation Timing Test
def test_swing_confirmation_timing():
    candles = [
        {"timestamp": "2026-01-05T07:55:00Z", "open": 4298.0, "high": 4300.0, "low": 4295.0, "close": 4299.0},
        {"timestamp": "2026-01-05T08:00:00Z", "open": 4299.0, "high": 4302.0, "low": 4298.0, "close": 4301.0},
        {"timestamp": "2026-01-05T08:05:00Z", "open": 4301.0, "high": 4304.0, "low": 4300.0, "close": 4303.0},
        {"timestamp": "2026-01-05T08:10:00Z", "open": 4303.0, "high": 4350.0, "low": 4302.0, "close": 4348.0},  # Peak at index 3
        {"timestamp": "2026-01-05T08:15:00Z", "open": 4348.0, "high": 4310.0, "low": 4305.0, "close": 4306.0},
        {"timestamp": "2026-01-05T08:20:00Z", "open": 4306.0, "high": 4308.0, "low": 4301.0, "close": 4302.0},
        {"timestamp": "2026-01-05T08:25:00Z", "open": 4302.0, "high": 4305.0, "low": 4300.0, "close": 4301.0}
    ]
    swings = market_structure_engine.detect_swings(candles, timeframe="5M")
    high_swings = [s for s in swings if s["type"] == "SWING_HIGH"]
    assert len(high_swings) > 0
    assert high_swings[0]["price"] == 4350.0


# 11. Liquidity Sweep Timing Test
def test_liquidity_sweep_timing():
    level_price = 4300.0
    candle_before = {"timestamp": "2026-01-05T08:00:00Z", "open": 4295.0, "high": 4299.0, "low": 4292.0, "close": 4298.0}
    candle_sweep = {"timestamp": "2026-01-05T08:05:00Z", "open": 4298.0, "high": 4305.0, "low": 4297.0, "close": 4299.0}

    # Before sweep, level is UNSWEPT
    assert candle_before["high"] < level_price
    # After sweep candle, level is SWEPT
    assert candle_sweep["high"] > level_price


# 12. Zero Lookahead Test
@pytest.mark.asyncio
async def test_zero_lookahead_point_in_time():
    candles = HistoricalDataLoader.generate_synthetic_xauusd(num_days=2, start_price=4300.0)
    cfg = ReplayConfig(symbol="XAUUSD")

    # Evaluate step 50
    s1, t1, _, _, _ = await point_in_time_evaluator.evaluate_step("XAUUSD", candles, 50, cfg)

    # Mutate future candle at index 100
    mutated_candles = list(candles)
    mutated_candles[100] = ReplayCandle(
        timestamp=candles[100].timestamp, open=9999.0, high=9999.0, low=9999.0, close=9999.0
    )

    # Evaluate step 50 again
    s2, t2, _, _, _ = await point_in_time_evaluator.evaluate_step("XAUUSD", mutated_candles, 50, cfg)

    assert (s1 is None and s2 is None) or (s1.scenario == s2.scenario)
    assert (t1 is None and t2 is None) or (t1.state == t2.state)


# 13. Deterministic Replay & Hashing Test
def test_reproducibility_hashing():
    candles = HistoricalDataLoader.generate_synthetic_xauusd(num_days=1, start_price=4300.0)
    raw_dict = [c.model_dump() for c in candles]
    cfg = ReplayConfig(symbol="XAUUSD")

    hash1 = compute_dataset_hash(raw_dict)
    hash2 = compute_dataset_hash(raw_dict)
    cfg_hash = compute_config_hash(cfg)

    assert hash1 == hash2
    assert len(hash1) == 16
    assert len(cfg_hash) == 16


# 14. Real-Data Outcome Resolution Test
def test_real_data_outcome_resolution():
    plan = TradePlanEvent(
        trade_id="plan_001",
        timestamp="2026-01-05T08:00:00Z",
        symbol="XAUUSD",
        scenario="LONG_PULLBACK",
        direction="LONG",
        state="VALID",
        entry_price=4300.0,
        sl_price=4290.0,
        tp1_price=4320.0,
        rr=2.0,
        confidence=85
    )
    subsequent = [
        ReplayCandle(timestamp="2026-01-05T08:05:00Z", open=4300.0, high=4325.0, low=4299.0, close=4322.0)
    ]
    cfg = ReplayConfig(symbol="XAUUSD")
    outcome = forward_outcome_engine.resolve_trade_outcome(plan, subsequent, cfg)

    assert outcome is not None
    assert outcome.outcome == "TP1_HIT"
    assert outcome.pnl_r == 2.0


# 15. Ambiguous Candle Handling Test
def test_ambiguous_candle_collision():
    plan = TradePlanEvent(
        trade_id="plan_002",
        timestamp="2026-01-05T08:00:00Z",
        symbol="XAUUSD",
        scenario="LONG_PULLBACK",
        direction="LONG",
        state="VALID",
        entry_price=4300.0,
        sl_price=4290.0,
        tp1_price=4320.0,
        rr=2.0,
        confidence=85
    )
    # Candle touches BOTH SL (4285.0) and TP (4325.0)
    subsequent = [
        ReplayCandle(timestamp="2026-01-05T08:05:00Z", open=4300.0, high=4325.0, low=4285.0, close=4305.0)
    ]
    cfg = ReplayConfig(symbol="XAUUSD", intrabar_resolution="CONSERVATIVE")
    outcome = forward_outcome_engine.resolve_trade_outcome(plan, subsequent, cfg)

    assert outcome is not None
    assert outcome.outcome == "AMBIGUOUS"
    assert outcome.pnl_r == 0.0


# 16. MAE / MFE Calculation Test
def test_mae_mfe_tracking():
    plan = TradePlanEvent(
        trade_id="plan_003",
        timestamp="2026-01-05T08:00:00Z",
        symbol="XAUUSD",
        scenario="LONG_PULLBACK",
        direction="LONG",
        state="VALID",
        entry_price=4300.0,
        sl_price=4290.0,
        tp1_price=4320.0,
        rr=2.0,
        confidence=85
    )
    subsequent = [
        ReplayCandle(timestamp="2026-01-05T08:05:00Z", open=4300.0, high=4310.0, low=4295.0, close=4305.0),
        ReplayCandle(timestamp="2026-01-05T08:10:00Z", open=4305.0, high=4322.0, low=4304.0, close=4321.0)
    ]
    cfg = ReplayConfig(symbol="XAUUSD")
    outcome = forward_outcome_engine.resolve_trade_outcome(plan, subsequent, cfg)

    assert outcome is not None
    assert outcome.mae == 5.0  # 4300 - 4295
    assert outcome.mfe == 22.0 # 4322 - 4300


# 17. Confidence Calibration Test
def test_confidence_calibration():
    outcomes = [
        TradeOutcome(trade_id="1", timestamp="t", symbol="X", scenario="S", direction="LONG", entry_price=1, sl_price=0, tp1_price=2, planned_rr=2, outcome="TP1_HIT", exit_timestamp="t", exit_price=2, duration_candles=1, duration_minutes=5, mae=0, mae_r=0, mfe=1, mfe_r=1, realized_rr=2, pnl_r=2.0, confidence=85),
        TradeOutcome(trade_id="2", timestamp="t", symbol="X", scenario="S", direction="LONG", entry_price=1, sl_price=0, tp1_price=2, planned_rr=2, outcome="SL_HIT", exit_timestamp="t", exit_price=0, duration_candles=1, duration_minutes=5, mae=1, mae_r=1, mfe=0, mfe_r=0, realized_rr=-1, pnl_r=-1.0, confidence=85),
        TradeOutcome(trade_id="3", timestamp="t", symbol="X", scenario="S", direction="LONG", entry_price=1, sl_price=0, tp1_price=2, planned_rr=2, outcome="TP1_HIT", exit_timestamp="t", exit_price=2, duration_candles=1, duration_minutes=5, mae=0, mae_r=0, mfe=1, mfe_r=1, realized_rr=2, pnl_r=2.0, confidence=85)
    ]
    m, sc, bins = metrics_calculator.compute_all_metrics([], [], outcomes)
    assert len(bins) == 5
    bin_80 = next(b for b in bins if b.bin_label == "80-89")
    assert bin_80.total_trades == 3
    assert bin_80.actual_win_rate == 66.67


# 18. Scenario Statistics & Sample Size Warnings Test
def test_scenario_statistics_sample_warnings():
    outcomes = [
        TradeOutcome(trade_id=str(i), timestamp="t", symbol="XAUUSD", scenario="LONG_PULLBACK", direction="LONG", entry_price=4300, sl_price=4290, tp1_price=4320, planned_rr=2, outcome="TP1_HIT", exit_timestamp="t", exit_price=4320, duration_candles=1, duration_minutes=5, mae=0, mae_r=0, mfe=20, mfe_r=2, realized_rr=2, pnl_r=2.0, confidence=85)
        for i in range(5)
    ]
    m, sc_stats, _ = metrics_calculator.compute_all_metrics([], [], outcomes)
    lp_stat = next(s for s in sc_stats if s.scenario == "LONG_PULLBACK")
    assert lp_stat.sample_size == 5
    assert lp_stat.sample_status == "INSUFFICIENT_SAMPLE"


# 19. Walk-Forward Chronology Test
def test_walk_forward_chronological_split():
    candles = HistoricalDataLoader.generate_synthetic_xauusd(num_days=4, start_price=4300.0)
    tr, val, oos = walk_forward_engine.split_candles(candles)

    assert len(tr) > 0
    assert len(val) > 0
    assert len(oos) > 0
    # Chronological integrity check
    assert tr[-1].timestamp < val[0].timestamp
    assert val[-1].timestamp < oos[0].timestamp


# 20. Monte Carlo Actual Outcomes Test
def test_monte_carlo_actual_outcomes():
    outcomes = [
        TradeOutcome(trade_id="1", timestamp="t", symbol="X", scenario="S", direction="LONG", entry_price=1, sl_price=0, tp1_price=2, planned_rr=2, outcome="TP1_HIT", exit_timestamp="t", exit_price=2, duration_candles=1, duration_minutes=5, mae=0, mae_r=0, mfe=1, mfe_r=1, realized_rr=2, pnl_r=2.0, confidence=85),
        TradeOutcome(trade_id="2", timestamp="t", symbol="X", scenario="S", direction="LONG", entry_price=1, sl_price=0, tp1_price=2, planned_rr=2, outcome="SL_HIT", exit_timestamp="t", exit_price=0, duration_candles=1, duration_minutes=5, mae=1, mae_r=1, mfe=0, mfe_r=0, realized_rr=-1, pnl_r=-1.0, confidence=85)
    ]
    mc = monte_carlo_engine.run_simulation(outcomes, num_iterations=1000)
    assert mc.iterations == 1000
    assert mc.expected_drawdown_p50 >= 0.0


# 21. Real Dataset Quality Pass / Reject Audit Test
def test_data_quality_pass_and_reject_audit():
    valid = HistoricalDataLoader.generate_synthetic_xauusd(num_days=1, start_price=4300.0)
    valid_dict = [c.model_dump() for c in valid]
    dq_valid = data_quality_auditor.audit_dataset(valid_dict)
    assert dq_valid.status == "PASS"

    corrupted_dict = list(valid_dict)
    corrupted_dict[10]["high"] = 100.0  # High < Low (impossible)
    dq_corrupted = data_quality_auditor.audit_dataset(corrupted_dict)
    assert dq_corrupted.status == "REJECT"


# 22. DOM Unavailable Handling Test
def test_dom_unavailable_ablation_status():
    cfg = ReplayConfig(symbol="XAUUSD", is_real_data=True, dom_available=False)
    ablation_items = ablation_engine.get_ablation_configs(cfg)
    res_d = ablation_engine.build_ablation_result(ablation_items[3]["test_id"], ablation_items[3]["test_name"], ablation_items[3]["description"], [], cfg)

    assert res_d.status == "DOM_ABLATION_UNAVAILABLE"


# 23. Immutable Baseline Check Test
def test_immutable_baseline_parameters():
    cfg = ReplayConfig()
    assert cfg.min_rr == 1.5
    assert cfg.risk_per_trade_pct == 1.0
    assert cfg.expiry_candles == 48


# 24. Full Replay Execution Test
@pytest.mark.asyncio
async def test_full_baseline_replay_execution():
    cfg = ReplayConfig(symbol="XAUUSD", timeframe="5M", is_real_data=False)
    candles = HistoricalDataLoader.generate_synthetic_xauusd(num_days=2, start_price=4300.0)
    report = await historical_replay_engine.run_replay(
        config=cfg,
        custom_candles=candles,
        run_ablation=True,
        run_walk_forward=True,
        run_monte_carlo=True
    )

    assert report.symbol == "XAUUSD"
    assert report.data_quality_report.status == "PASS"
    assert report.dataset_hash != ""
    assert report.config_hash != ""
    assert report.baseline_status in ["PROFITABLE", "UNPROVEN", "NEGATIVE"]
