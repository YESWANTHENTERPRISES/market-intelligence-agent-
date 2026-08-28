import csv
import json
import math
import os
from datetime import datetime, timedelta
from typing import List, Dict, Any
from app.replay.models import ReplayCandle


class HistoricalDataLoader:
    """
    Historical Candle Data Loader for Market Replay.
    Loads candles from CSV, JSON, or generates deterministic, high-fidelity synthetic candles.
    Also provides multi-timeframe candle aggregation (5M -> 15M -> 1H -> 4H -> 1D).
    """

    @staticmethod
    def load_from_csv(filepath: str, timeframe: str = "5M") -> List[ReplayCandle]:
        if not os.path.exists(filepath):
            raise FileNotFoundError(f"Historical CSV file not found: {filepath}")

        candles = []
        with open(filepath, mode="r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                ts = row.get("timestamp") or row.get("time") or row.get("Date") or ""
                o = float(row.get("open") or row.get("Open") or 0.0)
                h = float(row.get("high") or row.get("High") or 0.0)
                l = float(row.get("low") or row.get("Low") or 0.0)
                c = float(row.get("close") or row.get("Close") or 0.0)
                v = float(row.get("volume") or row.get("Volume") or 0.0)

                if o > 0 and h > 0 and l > 0 and c > 0:
                    candles.append(ReplayCandle(
                        timestamp=ts, open=o, high=h, low=l, close=c, volume=v, timeframe=timeframe
                    ))
        return sorted(candles, key=lambda x: x.timestamp)

    @staticmethod
    def load_from_json(filepath: str, timeframe: str = "5M") -> List[ReplayCandle]:
        if not os.path.exists(filepath):
            raise FileNotFoundError(f"Historical JSON file not found: {filepath}")

        with open(filepath, mode="r", encoding="utf-8") as f:
            raw_data = json.load(f)

        candles = []
        items = raw_data if isinstance(raw_data, list) else raw_data.get("candles", [])
        for item in items:
            ts = str(item.get("timestamp") or item.get("time") or "")
            o = float(item.get("open", 0.0))
            h = float(item.get("high", 0.0))
            l = float(item.get("low", 0.0))
            c = float(item.get("close", 0.0))
            v = float(item.get("volume", 0.0))
            if o > 0 and h > 0 and l > 0 and c > 0:
                candles.append(ReplayCandle(
                    timestamp=ts, open=o, high=h, low=l, close=c, volume=v, timeframe=timeframe
                ))
        return sorted(candles, key=lambda x: x.timestamp)

    @staticmethod
    def generate_synthetic_xauusd(
        num_days: int = 14,
        start_price: float = 4300.0,
        start_date_str: str = "2026-01-05T00:00:00Z"
    ) -> List[ReplayCandle]:
        """
        Generates realistic 5M XAUUSD candles with structural swings, FVGs, liquidity sweeps,
        and session volatility cycles (Asia low volatility, London expansion, NY volatility peak).
        """
        start_dt = datetime.fromisoformat(start_date_str.replace("Z", "+00:00"))
        candles: List[ReplayCandle] = []

        curr_price = start_price
        curr_time = start_dt

        # Total 5M bars: 288 per 24 hours
        total_bars = num_days * 288

        # Structural wave parameters
        trend_direction = -1.0  # Start with bearish trend to trigger SHORT_PULLBACK / SHORT_REVERSAL setups
        wave_period = 72  # ~6 hours wave
        atr_base = 3.5  # XAUUSD 5M ATR ~ $3.50

        for i in range(total_bars):
            hour = curr_time.hour

            # Session volatility multiplier
            if 7 <= hour < 12:  # London
                vol_mult = 1.6
            elif 12 <= hour < 17:  # NY
                vol_mult = 2.2
            elif 17 <= hour < 21:  # US afternoon
                vol_mult = 1.1
            else:  # Asia
                vol_mult = 0.6

            # Reverse structural trend every 2 days
            if i % (288 * 2) == 0 and i > 0:
                trend_direction *= -1.0

            # Sine wave oscillation + trend + noise
            wave = math.sin(2 * math.pi * (i % wave_period) / wave_period)
            drift = (trend_direction * 0.4 * atr_base * vol_mult) + (wave * 0.8 * atr_base)

            # Create discrete candle components
            open_p = round(curr_price, 2)

            # Periodic liquidity sweep spike every 144 bars (~12 hours)
            if i > 0 and i % 144 == 0:
                if trend_direction < 0:
                    # Bullish liquidity sweep spike up before dumping (classic SHORT setup)
                    high_p = open_p + (atr_base * 2.8 * vol_mult)
                    close_p = open_p - (atr_base * 1.2 * vol_mult)
                    low_p = close_p - (atr_base * 0.5 * vol_mult)
                else:
                    # Bearish liquidity sweep spike down before pumping (classic LONG setup)
                    low_p = open_p - (atr_base * 2.8 * vol_mult)
                    close_p = open_p + (atr_base * 1.2 * vol_mult)
                    high_p = close_p + (atr_base * 0.5 * vol_mult)
            else:
                change = drift + (math.cos(i * 0.5) * atr_base * 0.4)
                close_p = open_p + change
                high_p = max(open_p, close_p) + (abs(math.sin(i)) * atr_base * 0.7 * vol_mult)
                low_p = min(open_p, close_p) - (abs(math.cos(i)) * atr_base * 0.7 * vol_mult)

            # Round prices to 2 decimals for XAUUSD
            open_p = round(open_p, 2)
            high_p = round(max(high_p, open_p, close_p), 2)
            low_p = round(min(low_p, open_p, close_p), 2)
            close_p = round(close_p, 2)
            volume = round(1000.0 * vol_mult * (1.0 + abs(close_p - open_p)), 1)

            candles.append(ReplayCandle(
                timestamp=curr_time.strftime("%Y-%m-%dT%H:%M:%SZ"),
                open=open_p,
                high=high_p,
                low=low_p,
                close=close_p,
                volume=volume,
                timeframe="5M"
            ))

            curr_price = close_p
            curr_time += timedelta(minutes=5)

        return candles

    @staticmethod
    def aggregate_timeframes(base_candles: List[ReplayCandle]) -> Dict[str, List[Dict[str, Any]]]:
        """
        Aggregates 5M base candles into 5M, 15M, 1H, 4H, 1D candle structures
        for multi-timeframe analysis.
        """
        tf_data: Dict[str, List[Dict[str, Any]]] = {
            "5M": [c.model_dump() for c in base_candles],
            "15M": [],
            "1H": [],
            "4H": [],
            "1D": []
        }

        # Helper function for grouping and building HTF candles
        def group_and_build(group_size: int, tf_name: str):
            res = []
            for idx in range(0, len(base_candles), group_size):
                chunk = base_candles[idx:idx + group_size]
                if not chunk:
                    continue
                o = chunk[0].open
                h = max(c.high for c in chunk)
                l = min(c.low for c in chunk)
                c = chunk[-1].close
                v = sum(c.volume for c in chunk)
                ts = chunk[0].timestamp
                res.append({
                    "timestamp": ts, "open": o, "high": h, "low": l, "close": c, "volume": v, "timeframe": tf_name
                })
            return res

        tf_data["15M"] = group_and_build(3, "15M")
        tf_data["1H"] = group_and_build(12, "1H")
        tf_data["4H"] = group_and_build(48, "4H")
        tf_data["1D"] = group_and_build(288, "1D")

        return tf_data
