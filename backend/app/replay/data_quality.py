from datetime import datetime
from typing import List, Dict, Any, Tuple
from pydantic import BaseModel


class DataQualityReport(BaseModel):
    total_candles: int
    valid_candles: int
    invalid_candles: int
    duplicates: int
    missing_intervals: int
    first_timestamp: str
    last_timestamp: str
    timeframe: str
    coverage_days: float
    status: str  # PASS / REJECT
    issues: List[str]


class DataQualityAuditor:
    """
    Audits historical market dataset quality prior to replay.
    Enforces timestamp monotonicity, duplicate checks, OHLC sanity, and missing candle detection.
    Rejects corrupted datasets.
    """

    def audit_dataset(
        self,
        candles: List[Dict[str, Any]],
        expected_timeframe: str = "5M"
    ) -> DataQualityReport:
        if not candles:
            return DataQualityReport(
                total_candles=0,
                valid_candles=0,
                invalid_candles=0,
                duplicates=0,
                missing_intervals=0,
                first_timestamp="",
                last_timestamp="",
                timeframe=expected_timeframe,
                coverage_days=0.0,
                status="REJECT",
                issues=["Empty dataset provided."]
            )

        total_candles = len(candles)
        valid_candles = 0
        invalid_candles = 0
        duplicates = 0
        missing_intervals = 0
        issues: List[str] = []

        seen_timestamps = set()
        prev_dt = None

        timeframe_minutes_map = {
            "1M": 1,
            "5M": 5,
            "15M": 15,
            "1H": 60,
            "4H": 240,
            "1D": 1440
        }
        expected_delta_mins = timeframe_minutes_map.get(expected_timeframe, 5)

        for idx, candle in enumerate(candles):
            ts = candle.get("timestamp")
            o = float(candle.get("open", 0))
            h = float(candle.get("high", 0))
            l = float(candle.get("low", 0))
            c = float(candle.get("close", 0))

            candle_valid = True

            # 1. Price checks
            if o <= 0 or h <= 0 or l <= 0 or c <= 0:
                issues.append(f"Candle {idx} at {ts} has non-positive prices.")
                candle_valid = False

            if h < max(o, c) or l > min(o, c) or h < l:
                issues.append(f"Candle {idx} at {ts} violates OHLC geometry: O={o}, H={h}, L={l}, C={c}.")
                candle_valid = False

            # 2. Duplicate check
            if ts in seen_timestamps:
                duplicates += 1
                issues.append(f"Duplicate timestamp {ts} found at index {idx}.")
                candle_valid = False
            else:
                seen_timestamps.add(ts)

            # 3. Monotonicity & missing interval check
            try:
                curr_dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                if prev_dt is not None:
                    if curr_dt <= prev_dt:
                        issues.append(f"Non-monotonic timestamp {ts} at index {idx} (prev={prev_dt.isoformat()}).")
                        candle_valid = False
                    else:
                        diff_mins = (curr_dt - prev_dt).total_seconds() / 60.0
                        if diff_mins > expected_delta_mins * 1.5:
                            is_weekend = (prev_dt.weekday() == 4 and curr_dt.weekday() == 6)
                            if not is_weekend and diff_mins > expected_delta_mins * 3:
                                missing_intervals += int(diff_mins / expected_delta_mins) - 1
            except Exception as e:
                issues.append(f"Invalid timestamp format at index {idx}: {ts} ({str(e)}).")
                candle_valid = False

            if candle_valid:
                valid_candles += 1
                prev_dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            else:
                invalid_candles += 1

        first_ts = candles[0].get("timestamp", "")
        last_ts = candles[-1].get("timestamp", "")

        try:
            start_dt = datetime.fromisoformat(first_ts.replace("Z", "+00:00"))
            end_dt = datetime.fromisoformat(last_ts.replace("Z", "+00:00"))
            cov_days = round((end_dt - start_dt).total_seconds() / 86400.0, 2)
        except Exception:
            cov_days = 0.0

        status = "PASS" if invalid_candles == 0 and duplicates == 0 else "REJECT"

        return DataQualityReport(
            total_candles=total_candles,
            valid_candles=valid_candles,
            invalid_candles=invalid_candles,
            duplicates=duplicates,
            missing_intervals=missing_intervals,
            first_timestamp=first_ts,
            last_timestamp=last_ts,
            timeframe=expected_timeframe,
            coverage_days=cov_days,
            status=status,
            issues=issues[:50]
        )


data_quality_auditor = DataQualityAuditor()
