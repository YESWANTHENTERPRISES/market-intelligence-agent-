from typing import List, Tuple
from app.replay.models import ReplayCandle, WalkForwardPartition, WalkForwardResult, TradeOutcome
from app.replay.metrics import metrics_calculator


class WalkForwardEngine:
    """
    Walk-Forward Partitioning & Out-Of-Sample Validation Engine.
    Splits datasets into TRAIN (50%), VALIDATION (25%), and OUT_OF_SAMPLE (25%)
    to verify model stability and prevent historical curve-fitting.
    """

    def split_candles(self, candles: List[ReplayCandle]) -> Tuple[List[ReplayCandle], List[ReplayCandle], List[ReplayCandle]]:
        n = len(candles)
        if n < 3:
            return candles, [], []

        train_end = int(n * 0.50)
        val_end = int(n * 0.75)

        train_slice = candles[:train_end]
        val_slice = candles[train_end:val_end]
        oos_slice = candles[val_end:]

        return train_slice, val_slice, oos_slice

    def evaluate_walk_forward_partitions(
        self,
        train_outcomes: List[TradeOutcome],
        val_outcomes: List[TradeOutcome],
        oos_outcomes: List[TradeOutcome],
        train_dates: Tuple[str, str],
        val_dates: Tuple[str, str],
        oos_dates: Tuple[str, str]
    ) -> WalkForwardResult:
        
        m_train, _, _ = metrics_calculator.compute_all_metrics([], [], train_outcomes)
        m_val, _, _ = metrics_calculator.compute_all_metrics([], [], val_outcomes)
        m_oos, _, _ = metrics_calculator.compute_all_metrics([], [], oos_outcomes)

        part_train = WalkForwardPartition(
            partition_name="TRAIN (Development)",
            start_date=train_dates[0],
            end_date=train_dates[1],
            total_trades=len(train_outcomes),
            win_rate=m_train.win_rate,
            profit_factor=m_train.profit_factor,
            expectancy=m_train.expectancy,
            max_drawdown_pct=m_train.max_drawdown_pct
        )

        part_val = WalkForwardPartition(
            partition_name="VALIDATION",
            start_date=val_dates[0],
            end_date=val_dates[1],
            total_trades=len(val_outcomes),
            win_rate=m_val.win_rate,
            profit_factor=m_val.profit_factor,
            expectancy=m_val.expectancy,
            max_drawdown_pct=m_val.max_drawdown_pct
        )

        part_oos = WalkForwardPartition(
            partition_name="OUT_OF_SAMPLE (Forward Validation)",
            start_date=oos_dates[0],
            end_date=oos_dates[1],
            total_trades=len(oos_outcomes),
            win_rate=m_oos.win_rate,
            profit_factor=m_oos.profit_factor,
            expectancy=m_oos.expectancy,
            max_drawdown_pct=m_oos.max_drawdown_pct
        )

        # Stability index = OOS Expectancy / Train Expectancy
        train_exp = m_train.expectancy if m_train.expectancy != 0 else 0.01
        stability = round(m_oos.expectancy / train_exp, 2) if train_exp != 0 else 1.0

        return WalkForwardResult(
            partitions=[part_train, part_val, part_oos],
            in_sample_expectancy=m_train.expectancy,
            out_of_sample_expectancy=m_oos.expectancy,
            stability_index=stability
        )


walk_forward_engine = WalkForwardEngine()
