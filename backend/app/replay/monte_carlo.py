import random
from typing import List
from app.replay.models import TradeOutcome, MonteCarloResult


class MonteCarloEngine:
    """
    Monte Carlo Risk & Equity Curve Simulator.
    Resamples historical trade outcomes across 5,000+ trials to calculate:
    - Expected max drawdown percentiles (50th, 95th, 99th)
    - Worst losing streak distribution
    - Risk of ruin (% probability of hitting >= 20% drawdown)
    - Equity curve variability bands
    """

    def run_simulation(
        self,
        trade_outcomes: List[TradeOutcome],
        num_iterations: int = 10000,
        initial_balance: float = 10000.0,
        risk_per_trade_pct: float = 1.0,
        ruin_threshold_pct: float = 20.0
    ) -> MonteCarloResult:
        if not trade_outcomes:
            return MonteCarloResult(iterations=num_iterations)

        pnl_r_list = [t.pnl_r for t in trade_outcomes]
        num_trades = len(pnl_r_list)

        drawdowns: List[float] = []
        max_streaks: List[int] = []
        ruin_count = 0
        sample_curves: List[List[float]] = []

        # Fix seed for deterministic reproducible Monte Carlo results
        random.seed(42)

        for it in range(num_iterations):
            # Resample with replacement
            resampled = [random.choice(pnl_r_list) for _ in range(num_trades)]

            balance = initial_balance
            peak = initial_balance
            max_dd_pct = 0.0
            curr_streak = 0
            max_streak = 0
            curve = [round(balance, 2)]

            for r in resampled:
                # Dollar PnL per trade
                risk_dollars = balance * (risk_per_trade_pct / 100.0)
                pnl = r * risk_dollars
                balance += pnl

                if r < 0:
                    curr_streak += 1
                    if curr_streak > max_streak:
                        max_streak = curr_streak
                else:
                    curr_streak = 0

                if balance > peak:
                    peak = balance

                dd = round(((peak - balance) / peak) * 100.0, 2) if peak > 0 else 0.0
                if dd > max_dd_pct:
                    max_dd_pct = dd

                if it < 5 and len(curve) < 100:
                    curve.append(round(balance, 2))

            if it < 5:
                sample_curves.append(curve)

            drawdowns.append(max_dd_pct)
            max_streaks.append(max_streak)

            if max_dd_pct >= ruin_threshold_pct:
                ruin_count += 1

        drawdowns.sort()
        max_streaks.sort()

        p50_idx = int(num_iterations * 0.50)
        p95_idx = int(num_iterations * 0.95)
        p99_idx = int(num_iterations * 0.99)

        p50_dd = round(drawdowns[min(p50_idx, num_iterations - 1)], 2)
        p95_dd = round(drawdowns[min(p95_idx, num_iterations - 1)], 2)
        p99_dd = round(drawdowns[min(p99_idx, num_iterations - 1)], 2)

        med_streak = max_streaks[min(p50_idx, num_iterations - 1)] if max_streaks else 0
        p95_streak = max_streaks[min(p95_idx, num_iterations - 1)] if max_streaks else 0
        worst_streak = max(max_streaks) if max_streaks else 0
        risk_of_ruin = round((ruin_count / num_iterations) * 100.0, 2)

        return MonteCarloResult(
            iterations=num_iterations,
            expected_drawdown_p50=p50_dd,
            expected_drawdown_p95=p95_dd,
            expected_drawdown_p99=p99_dd,
            median_losing_streak=med_streak,
            p95_losing_streak=p95_streak,
            worst_losing_streak=worst_streak,
            risk_of_ruin_pct=risk_of_ruin,
            equity_curves_sample=sample_curves
        )


monte_carlo_engine = MonteCarloEngine()
