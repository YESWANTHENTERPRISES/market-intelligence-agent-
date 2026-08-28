from fastapi import APIRouter, HTTPException, Query, Body
from typing import Optional, List, Dict, Any
from app.replay.models import ReplayConfig, ReplayReport, MonteCarloResult, WalkForwardResult
from app.replay.engine import historical_replay_engine
from app.replay.monte_carlo import monte_carlo_engine

router = APIRouter(prefix="/api/replay", tags=["Historical Replay"])


@router.post("/run", response_model=ReplayReport)
async def run_replay(config: Optional[ReplayConfig] = Body(None)):
    """
    Executes a candle-by-candle historical replay simulation for XAUUSD with zero lookahead bias.
    Returns complete strategy validation metrics, scenario statistics, calibration, ablation, & Monte Carlo simulations.
    """
    try:
        report = await historical_replay_engine.run_replay(
            config=config or ReplayConfig(),
            run_ablation=True,
            run_walk_forward=True,
            run_monte_carlo=True
        )
        return report
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Replay execution failed: {str(e)}")


@router.post("/ablation")
async def run_ablation(config: Optional[ReplayConfig] = Body(None)):
    """
    Executes an ablation test suite across 5 feature configurations (PA Only -> Full System).
    """
    try:
        report = await historical_replay_engine.run_replay(
            config=config or ReplayConfig(),
            run_ablation=True,
            run_walk_forward=False,
            run_monte_carlo=False
        )
        return {
            "symbol": report.symbol,
            "ablation_results": report.ablation_results
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ablation testing failed: {str(e)}")


@router.post("/walk-forward", response_model=Optional[WalkForwardResult])
async def run_walk_forward(config: Optional[ReplayConfig] = Body(None)):
    """
    Executes Walk-Forward train/validation/OOS dataset partitioning.
    """
    try:
        report = await historical_replay_engine.run_replay(
            config=config or ReplayConfig(),
            run_ablation=False,
            run_walk_forward=True,
            run_monte_carlo=False
        )
        return report.walk_forward_results
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Walk-forward evaluation failed: {str(e)}")


@router.post("/monte-carlo", response_model=Optional[MonteCarloResult])
async def run_monte_carlo(config: Optional[ReplayConfig] = Body(None)):
    """
    Executes a 2,500+ trial Monte Carlo risk simulation on historical trade outcomes.
    """
    try:
        report = await historical_replay_engine.run_replay(
            config=config or ReplayConfig(),
            run_ablation=False,
            run_walk_forward=False,
            run_monte_carlo=True
        )
        return report.monte_carlo_results or MonteCarloResult(iterations=0)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Monte Carlo simulation failed: {str(e)}")
