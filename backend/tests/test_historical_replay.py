import pytest
import asyncio
from fastapi.testclient import TestClient
from app.main import app
from app.replay.models import (
    ReplayCandle, ReplayConfig, TradePlanEvent, TradeOutcome
)
from app.replay.data_loader import HistoricalDataLoader
from app.replay.point_in_time import point_in_time_evaluator
from app.replay.outcome_engine import forward_outcome_engine
from app.replay.metrics import metrics_calculator
from app.replay.ablation import ablation_engine
from app.replay.walk_forward import walk_forward_engine
from app.replay.monte_carlo import monte_carlo_engine
from app.replay.engine import historical_replay_engine

client = TestClient(app)


def test_synthetic_data_loader():
    candles = HistoricalDataLoader.generate_synthetic_xauusd(num_days=2, start_price=4300.0)
    assert len(candles) == 2 * 288
    assert candles[0].timeframe == "5M"
    assert candles[0].open > 0
    assert candles[0].high >= candles[0].low

    tf_data = HistoricalDataLoader.aggregate_timeframes(candles)
    assert "5M" in tf_data
    assert "15M" in tf_data
    assert "1H" in tf_data
    assert "4H" in tf_data
    assert "1D" in tf_data
    assert len(tf_data["15M"]) == len(candles) // 3
    assert len(tf_data["1H"]) == len(candles) // 12


@pytest.mark.asyncio
async def test_point_in_time_zero_lookahead():
    candles = HistoricalDataLoader.generate_synthetic_xauusd(num_days=2, start_price=4300.0)
    cfg = ReplayConfig()

    # Evaluate at step 50
    s_evt50, t_evt50, ctx50, lvl50, val50 = await point_in_time_evaluator.evaluate_step(
        symbol="XAUUSD", all_5m_candles=candles, step_index=50, config=cfg
    )

    # Mutate future candle (step 100) high price drastically
    candles_mutated = [c.model_copy() for c in candles]
    candles_mutated[100].high = 9999.00
    candles_mutated[100].close = 9999.00

    # Evaluate at step 50 again on mutated future series
    s_evt50_mut, t_evt50_mut, ctx50_mut, lvl50_mut, val50_mut = await point_in_time_evaluator.evaluate_step(
        symbol="XAUUSD", all_5m_candles=candles_mutated, step_index=50, config=cfg
    )

    # State at step 50 MUST be 100% identical despite future mutation
    assert val50.state == val50_mut.state
    assert ctx50.market_bias == ctx50_mut.market_bias
    if s_evt50 and s_evt50_mut:
        assert s_evt50.score == s_evt50_mut.score
        assert s_evt50.price == s_evt50_mut.price


def test_forward_outcome_tp_sl_hits():
    cfg = ReplayConfig(expiry_candles=20, intrabar_resolution="CONSERVATIVE")
    plan_long = TradePlanEvent(
        trade_id="plan_1",
        timestamp="2026-01-05T10:00:00Z",
        symbol="XAUUSD",
        scenario="LONG_PULLBACK",
        direction="LONG",
        state="VALID",
        entry_price=4300.00,
        sl_price=4295.00,
        tp1_price=4310.00,
        tp2_price=4320.00,
        rr=2.0
    )

    subsequent_win = [
        ReplayCandle(timestamp="2026-01-05T10:05:00Z", open=4300.0, high=4305.0, low=4299.0, close=4304.0),
        ReplayCandle(timestamp="2026-01-05T10:10:00Z", open=4304.0, high=4312.0, low=4303.0, close=4311.0)
    ]

    outcome_win = forward_outcome_engine.resolve_trade_outcome(plan_long, subsequent_win, cfg)
    assert outcome_win is not None
    assert outcome_win.outcome in ["TP1_HIT", "TP2_HIT", "TP3_HIT"]
    assert outcome_win.pnl_r > 0
    assert outcome_win.mfe == 12.0
    assert outcome_win.mae == 1.0

    subsequent_loss = [
        ReplayCandle(timestamp="2026-01-05T10:05:00Z", open=4300.0, high=4301.0, low=4294.0, close=4295.0)
    ]
    outcome_loss = forward_outcome_engine.resolve_trade_outcome(plan_long, subsequent_loss, cfg)
    assert outcome_loss is not None
    assert outcome_loss.outcome == "SL_HIT"
    assert outcome_loss.pnl_r == -1.0


def test_intrabar_ambiguity_handling():
    cfg_conservative = ReplayConfig(intrabar_resolution="CONSERVATIVE")
    plan_short = TradePlanEvent(
        trade_id="plan_amb",
        timestamp="2026-01-05T12:00:00Z",
        symbol="XAUUSD",
        scenario="SHORT_PULLBACK",
        direction="SHORT",
        state="VALID",
        entry_price=4350.00,
        sl_price=4355.00,
        tp1_price=4340.00,
        rr=2.0
    )

    # Candle range encompasses both SL (4355) and TP1 (4340)
    ambiguous_candle = [
        ReplayCandle(timestamp="2026-01-05T12:05:00Z", open=4350.0, high=4357.0, low=4338.0, close=4345.0)
    ]

    outcome = forward_outcome_engine.resolve_trade_outcome(plan_short, ambiguous_candle, cfg_conservative)
    assert outcome is not None
    assert outcome.outcome == "AMBIGUOUS"
    assert outcome.pnl_r == 0.0  # Conservative: does not award positive PnL to ambiguous trades


def test_mae_mfe_calculations():
    cfg = ReplayConfig()
    plan = TradePlanEvent(
        trade_id="plan_mae_mfe",
        timestamp="2026-01-05T10:00:00Z",
        symbol="XAUUSD",
        scenario="LONG_REVERSAL",
        direction="LONG",
        state="VALID",
        entry_price=4300.00,
        sl_price=4290.00,  # risk_dist = 10
        tp1_price=4320.00,
        rr=2.0
    )

    candles = [
        ReplayCandle(timestamp="2026-01-05T10:05:00Z", open=4300.0, high=4310.0, low=4296.0, close=4305.0),
        ReplayCandle(timestamp="2026-01-05T10:10:00Z", open=4305.0, high=4308.0, low=4293.0, close=4298.0),
        ReplayCandle(timestamp="2026-01-05T10:15:00Z", open=4298.0, high=4322.0, low=4297.0, close=4321.0)
    ]

    outcome = forward_outcome_engine.resolve_trade_outcome(plan, candles, cfg)
    assert outcome is not None
    assert outcome.mae == 7.0  # Lowest low 4293 -> 4300 - 4293 = 7.0
    assert outcome.mae_r == 0.70  # 7.0 / 10.0
    assert outcome.mfe == 22.0  # Highest high 4322 -> 4322 - 4300 = 22.0
    assert outcome.mfe_r == 2.20  # 22.0 / 10.0


def test_metrics_calculator():
    outcomes = [
        TradeOutcome(
            trade_id="t1", timestamp="ts1", symbol="XAUUSD", scenario="SHORT_PULLBACK", direction="SHORT",
            entry_price=4300.0, sl_price=4305.0, tp1_price=4290.0, planned_rr=2.0, outcome="TP1_HIT",
            exit_timestamp="ts1_e", exit_price=4290.0, duration_candles=3, duration_minutes=15,
            mae=1.0, mae_r=0.2, mfe=10.0, mfe_r=2.0, realized_rr=2.0, pnl_r=2.0, pnl_dollars=200.0, confidence=85
        ),
        TradeOutcome(
            trade_id="t2", timestamp="ts2", symbol="XAUUSD", scenario="SHORT_PULLBACK", direction="SHORT",
            entry_price=4300.0, sl_price=4305.0, tp1_price=4290.0, planned_rr=2.0, outcome="SL_HIT",
            exit_timestamp="ts2_e", exit_price=4305.0, duration_candles=2, duration_minutes=10,
            mae=5.0, mae_r=1.0, mfe=2.0, mfe_r=0.4, realized_rr=-1.0, pnl_r=-1.0, pnl_dollars=-100.0, confidence=82
        )
    ]

    metrics, sc_stats, calib = metrics_calculator.compute_all_metrics([], [], outcomes)

    assert metrics.wins == 1
    assert metrics.losses == 1
    assert metrics.win_rate == 50.0
    assert metrics.profit_factor == 2.0
    assert metrics.expectancy == 0.50
    assert metrics.max_drawdown_pct > 0
    assert len(sc_stats) == 1
    assert sc_stats[0].scenario == "SHORT_PULLBACK"
    assert sc_stats[0].win_rate == 50.0


def test_ablation_engine_configs():
    base_cfg = ReplayConfig()
    configs = ablation_engine.get_ablation_configs(base_cfg)
    assert len(configs) == 5
    assert configs[0]["test_id"] == "A"
    assert configs[0]["config"].enable_dom is False
    assert configs[4]["test_id"] == "E"
    assert configs[4]["config"].enable_dom is True


def test_walk_forward_partitioning():
    candles = HistoricalDataLoader.generate_synthetic_xauusd(num_days=4, start_price=4300.0)
    tr, val, oos = walk_forward_engine.split_candles(candles)
    assert len(tr) + len(val) + len(oos) == len(candles)
    assert len(tr) == len(candles) // 2


def test_monte_carlo_simulation():
    outcomes = [
        TradeOutcome(
            trade_id=f"t_{i}", timestamp="ts", symbol="XAUUSD", scenario="SHORT_PULLBACK", direction="SHORT",
            entry_price=4300.0, sl_price=4305.0, tp1_price=4290.0, planned_rr=2.0,
            outcome="TP1_HIT" if i % 2 == 0 else "SL_HIT", exit_timestamp="ts_e", exit_price=4290.0,
            duration_candles=3, duration_minutes=15, mae=1.0, mae_r=0.2, mfe=10.0, mfe_r=2.0,
            realized_rr=2.0 if i % 2 == 0 else -1.0, pnl_r=2.0 if i % 2 == 0 else -1.0,
            pnl_dollars=200.0 if i % 2 == 0 else -100.0, confidence=80
        )
        for i in range(20)
    ]

    res = monte_carlo_engine.run_simulation(outcomes, num_iterations=500)
    assert res.iterations == 500
    assert res.expected_drawdown_p50 >= 0
    assert res.expected_drawdown_p95 >= res.expected_drawdown_p50
    assert res.worst_losing_streak > 0
    assert len(res.equity_curves_sample) > 0


@pytest.mark.asyncio
async def test_full_historical_replay_execution():
    cfg = ReplayConfig(symbol="XAUUSD", timeframe="5M", expiry_candles=24)
    candles = HistoricalDataLoader.generate_synthetic_xauusd(num_days=2, start_price=4300.0)
    report = await historical_replay_engine.run_replay(
        config=cfg,
        custom_candles=candles,
        run_ablation=True,
        run_walk_forward=True,
        run_monte_carlo=True
    )

    assert report.symbol == "XAUUSD"
    assert report.total_candles_processed > 100
    assert report.metrics is not None
    assert report.metrics.total_setups > 0
    assert len(report.scenario_statistics) > 0
    assert len(report.confidence_calibration) == 5
    assert len(report.ablation_results) == 5
    assert report.walk_forward_results is not None
    assert report.monte_carlo_results is not None


def test_replay_api_endpoints():
    candles = HistoricalDataLoader.generate_synthetic_xauusd(num_days=1, start_price=4300.0)

    res = client.post("/api/replay/run", json={"symbol": "XAUUSD", "timeframe": "5M"})
    assert res.status_code == 200
    data = res.json()
    assert "metrics" in data
    assert "scenario_statistics" in data
    assert "ablation_results" in data
    assert len(data["ablation_results"]) == 5

    res_abl = client.post("/api/replay/ablation", json={"symbol": "XAUUSD"})
    assert res_abl.status_code == 200
    assert "ablation_results" in res_abl.json()

    res_wf = client.post("/api/replay/walk-forward", json={"symbol": "XAUUSD"})
    assert res_wf.status_code == 200

    res_mc = client.post("/api/replay/monte-carlo", json={"symbol": "XAUUSD"})
    assert res_mc.status_code == 200
    assert "expected_drawdown_p50" in res_mc.json()
