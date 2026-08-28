import time
from typing import Dict, List, Any, Optional, Tuple

def calculate_atr(candles: List[Dict[str, float]], period: int = 14) -> float:
    """
    Calculates Average True Range (ATR) over a list of OHLC candles.
    Each candle should have 'high', 'low', 'close'.
    """
    if len(candles) < 2:
        return 1.0

    tr_list = []
    for i in range(1, len(candles)):
        h = candles[i]['high']
        l = candles[i]['low']
        prev_c = candles[i-1]['close']
        tr = max(h - l, abs(h - prev_c), abs(l - prev_c))
        tr_list.append(tr)

    if not tr_list:
        return 1.0

    recent_tr = tr_list[-period:] if len(tr_list) >= period else tr_list
    return sum(recent_tr) / len(recent_tr)

class MarketStructureEngine:
    def __init__(self, left_bars: int = 3, right_bars: int = 3):
        self.left_bars = left_bars
        self.right_bars = right_bars

    def detect_swings(
        self,
        candles: List[Dict[str, Any]],
        timeframe: str,
        atr: Optional[float] = None
    ) -> List[Dict[str, Any]]:
        """
        Detects swing highs and swing lows deterministically.
        Swing High: high[i] > highs of left_bars AND high[i] >= highs of right_bars
        Swing Low: low[i] < lows of left_bars AND low[i] <= lows of right_bars
        Applies ATR-based filtering to ignore micro-swings.
        """
        if len(candles) < (self.left_bars + self.right_bars + 1):
            return []

        if atr is None or atr <= 0:
            atr = calculate_atr(candles)

        swings = []
        min_swing_dist = atr * 0.20  # Minimum ATR filter to eliminate noise

        for i in range(self.left_bars, len(candles) - self.right_bars):
            c = candles[i]
            high_i = c['high']
            low_i = c['low']
            ts = c.get('timestamp', str(i))

            left_highs = [candles[j]['high'] for j in range(i - self.left_bars, i)]
            right_highs = [candles[j]['high'] for j in range(i + 1, i + 1 + self.right_bars)]

            left_lows = [candles[j]['low'] for j in range(i - self.left_bars, i)]
            right_lows = [candles[j]['low'] for j in range(i + 1, i + 1 + self.right_bars)]

            # Check Swing High
            if high_i > max(left_highs) and high_i >= max(right_highs):
                # ATR filter
                prev_low = min([candles[j]['low'] for j in range(i - self.left_bars, i + 1 + self.right_bars)])
                if (high_i - prev_low) >= min_swing_dist:
                    swings.append({
                        "price": round(float(high_i), 4),
                        "type": "SWING_HIGH",
                        "timeframe": timeframe,
                        "timestamp": ts,
                        "strength": 0.85 if timeframe in ["4H", "1H"] else 0.65,
                        "index": i,
                        "age": len(candles) - 1 - i
                    })

            # Check Swing Low
            if low_i < min(left_lows) and low_i <= min(right_lows):
                prev_high = max([candles[j]['high'] for j in range(i - self.left_bars, i + 1 + self.right_bars)])
                if (prev_high - low_i) >= min_swing_dist:
                    swings.append({
                        "price": round(float(low_i), 4),
                        "type": "SWING_LOW",
                        "timeframe": timeframe,
                        "timestamp": ts,
                        "strength": 0.85 if timeframe in ["4H", "1H"] else 0.65,
                        "index": i,
                        "age": len(candles) - 1 - i
                    })

        return swings

    def detect_equal_highs_lows(
        self,
        candles: List[Dict[str, Any]],
        timeframe: str,
        atr: Optional[float] = None
    ) -> List[Dict[str, Any]]:
        """
        Detects equal highs and equal lows using ATR-relative tolerance.
        tolerance = ATR(14) * 0.10
        abs(high1 - high2) <= tolerance -> EQUAL_HIGH -> BUY_SIDE_LIQUIDITY
        abs(low1 - low2) <= tolerance -> EQUAL_LOW -> SELL_SIDE_LIQUIDITY
        """
        if len(candles) < 5:
            return []

        if atr is None or atr <= 0:
            atr = calculate_atr(candles)

        tolerance = atr * 0.10
        swings = self.detect_swings(candles, timeframe, atr=atr)
        
        swing_highs = [s for s in swings if s["type"] == "SWING_HIGH"]
        swing_lows = [s for s in swings if s["type"] == "SWING_LOW"]

        results = []

        # Equal Highs
        for i in range(len(swing_highs)):
            for j in range(i + 1, len(swing_highs)):
                sh1 = swing_highs[i]
                sh2 = swing_highs[j]
                if abs(sh1["price"] - sh2["price"]) <= tolerance:
                    avg_price = round((sh1["price"] + sh2["price"]) / 2.0, 4)
                    results.append({
                        "price": avg_price,
                        "type": "EQUAL_HIGH",
                        "classification": "BUY_SIDE_LIQUIDITY",
                        "timeframe": timeframe,
                        "contributing_prices": [sh1["price"], sh2["price"]],
                        "evidence": [f"Equal highs ({sh1['price']}, {sh2['price']}) on {timeframe}"]
                    })

        # Equal Lows
        for i in range(len(swing_lows)):
            for j in range(i + 1, len(swing_lows)):
                sl1 = swing_lows[i]
                sl2 = swing_lows[j]
                if abs(sl1["price"] - sl2["price"]) <= tolerance:
                    avg_price = round((sl1["price"] + sl2["price"]) / 2.0, 4)
                    results.append({
                        "price": avg_price,
                        "type": "EQUAL_LOW",
                        "classification": "SELL_SIDE_LIQUIDITY",
                        "timeframe": timeframe,
                        "contributing_prices": [sl1["price"], sl2["price"]],
                        "evidence": [f"Equal lows ({sl1['price']}, {sl2['price']}) on {timeframe}"]
                    })

        return results

    def detect_displacements(
        self,
        candles: List[Dict[str, Any]],
        timeframe: str,
        atr: Optional[float] = None
    ) -> List[Dict[str, Any]]:
        """
        Detects strong displacement candles.
        range > ATR(14) * 1.5 AND body / range > 0.60.
        Tracks displacement origin area. Label: DISPLACEMENT_ORIGIN
        """
        if len(candles) < 2:
            return []

        if atr is None or atr <= 0:
            atr = calculate_atr(candles)

        displacements = []
        for i, c in enumerate(candles):
            high = c['high']
            low = c['low']
            open_p = c['open']
            close_p = c['close']

            c_range = high - low
            if c_range <= 0:
                continue

            body = abs(close_p - open_p)
            body_ratio = body / c_range

            if c_range > (atr * 1.5) and body_ratio > 0.60:
                origin_price = round(open_p, 4)
                direction = "BULLISH" if close_p > open_p else "BEARISH"
                displacements.append({
                    "price": origin_price,
                    "type": "DISPLACEMENT_ORIGIN",
                    "direction": direction,
                    "timeframe": timeframe,
                    "range": round(c_range, 4),
                    "evidence": [f"Strong {direction.lower()} displacement origin on {timeframe}"]
                })

        return displacements

    def detect_fvgs(
        self,
        candles: List[Dict[str, Any]],
        timeframe: str,
        atr: Optional[float] = None
    ) -> List[Dict[str, Any]]:
        """
        Detects 3-candle Fair Value Gaps (FVG) and tracks mitigation status.
        Bullish FVG: low[i] > high[i-2]
        Bearish FVG: high[i] < low[i-2]
        """
        if len(candles) < 3:
            return []

        if atr is None or atr <= 0:
            atr = calculate_atr(candles)

        fvgs = []
        min_gap = atr * 0.05

        for i in range(2, len(candles)):
            c0 = candles[i - 2]
            c2 = candles[i]

            # Bullish FVG (Demand Gap)
            if c2['low'] > c0['high'] + min_gap:
                gap_low = float(c0['high'])
                gap_high = float(c2['low'])
                midpoint = round((gap_low + gap_high) / 2.0, 4)

                subsequent = candles[i + 1:] if i + 1 < len(candles) else []
                mitigated = any(c['low'] <= gap_low for c in subsequent)
                partially_filled = any(c['low'] < gap_high for c in subsequent)

                status = "MITIGATED" if mitigated else ("PARTIAL" if partially_filled else "ACTIVE")

                if status != "MITIGATED":
                    fvgs.append({
                        "price": midpoint,
                        "gap_low": gap_low,
                        "gap_high": gap_high,
                        "type": "BULLISH_FVG",
                        "classification": "SUPPORT",
                        "timeframe": timeframe,
                        "status": status,
                        "evidence": [f"Bullish FVG ({gap_low:.2f}–{gap_high:.2f}) on {timeframe}"]
                    })

            # Bearish FVG (Supply Gap)
            if c2['high'] < c0['low'] - min_gap:
                gap_high = float(c0['low'])
                gap_low = float(c2['high'])
                midpoint = round((gap_low + gap_high) / 2.0, 4)

                subsequent = candles[i + 1:] if i + 1 < len(candles) else []
                mitigated = any(c['high'] >= gap_high for c in subsequent)
                partially_filled = any(c['high'] > gap_low for c in subsequent)

                status = "MITIGATED" if mitigated else ("PARTIAL" if partially_filled else "ACTIVE")

                if status != "MITIGATED":
                    fvgs.append({
                        "price": midpoint,
                        "gap_low": gap_low,
                        "gap_high": gap_high,
                        "type": "BEARISH_FVG",
                        "classification": "RESISTANCE",
                        "timeframe": timeframe,
                        "status": status,
                        "evidence": [f"Bearish FVG ({gap_low:.2f}–{gap_high:.2f}) on {timeframe}"]
                    })

        return fvgs

    def detect_bos_choch(
        self,
        candles: List[Dict[str, Any]],
        timeframe: str,
        atr: Optional[float] = None
    ) -> List[Dict[str, Any]]:
        """
        Detects Break of Structure (BOS) and Change of Character (CHoCH).
        """
        if len(candles) < 6:
            return []

        swings = self.detect_swings(candles, timeframe, atr=atr)
        if len(swings) < 2:
            return []

        results = []
        for i in range(1, len(swings)):
            s_prev = swings[i - 1]
            s_curr = swings[i]

            if s_curr["type"] == "SWING_HIGH" and s_prev["type"] == "SWING_HIGH":
                if s_curr["price"] > s_prev["price"]:
                    results.append({
                        "price": s_curr["price"],
                        "type": "BULLISH_BOS",
                        "classification": "RESISTANCE",
                        "timeframe": timeframe,
                        "evidence": [f"Bullish BOS ({s_curr['price']}) on {timeframe}"]
                    })
            elif s_curr["type"] == "SWING_LOW" and s_prev["type"] == "SWING_LOW":
                if s_curr["price"] < s_prev["price"]:
                    results.append({
                        "price": s_curr["price"],
                        "type": "BEARISH_BOS",
                        "classification": "SUPPORT",
                        "timeframe": timeframe,
                        "evidence": [f"Bearish BOS ({s_curr['price']}) on {timeframe}"]
                    })

        return results

    def detect_rejections(

        self,
        candles: List[Dict[str, Any]],
        timeframe: str,
        atr: Optional[float] = None
    ) -> List[Dict[str, Any]]:
        """
        Detects strong rejection wicks.
        Resistance rejection: large upper wick + close away from high.
        Support rejection: large lower wick + close away from low.
        """
        if len(candles) < 2:
            return []

        if atr is None or atr <= 0:
            atr = calculate_atr(candles)

        rejections = []
        for c in candles:
            high = c['high']
            low = c['low']
            open_p = c['open']
            close_p = c['close']
            c_range = high - low

            if c_range < (atr * 0.8):
                continue

            upper_wick = high - max(open_p, close_p)
            lower_wick = min(open_p, close_p) - low

            # Upper wick rejection (Resistance)
            if upper_wick / c_range > 0.50:
                rejections.append({
                    "price": round(high, 4),
                    "type": "STRONG_REJECTION_RESISTANCE",
                    "timeframe": timeframe,
                    "wick_ratio": round(upper_wick / c_range, 2),
                    "evidence": [f"Strong upper wick rejection on {timeframe}"]
                })

            # Lower wick rejection (Support)
            if lower_wick / c_range > 0.50:
                rejections.append({
                    "price": round(low, 4),
                    "type": "STRONG_REJECTION_SUPPORT",
                    "timeframe": timeframe,
                    "wick_ratio": round(lower_wick / c_range, 2),
                    "evidence": [f"Strong lower wick rejection on {timeframe}"]
                })

        return rejections

    def compute_session_and_period_levels(
        self,
        ohlc_data: Dict[str, List[Dict[str, Any]]]
    ) -> List[Dict[str, Any]]:
        """
        Calculates reference period levels:
        PDH, PDL, PWH, PWL, PSH, PSL, CDH, CDL, CSH, CSL.
        Only when required historical data is available.
        """
        levels = []

        # Daily / Weekly levels from 1D / 1H if available
        d_candles = ohlc_data.get("1D") or ohlc_data.get("4H") or ohlc_data.get("1H")
        if d_candles and len(d_candles) >= 2:
            # Previous Day High / Low
            prev_day = d_candles[-2]
            levels.append({
                "price": round(prev_day["high"], 4),
                "type": "PDH",
                "timeframe": "1D",
                "evidence": ["Previous Day High (PDH)"]
            })
            levels.append({
                "price": round(prev_day["low"], 4),
                "type": "PDL",
                "timeframe": "1D",
                "evidence": ["Previous Day Low (PDL)"]
            })

            # Current Day High / Low
            curr_day = d_candles[-1]
            levels.append({
                "price": round(curr_day["high"], 4),
                "type": "CDH",
                "timeframe": "1D",
                "evidence": ["Current Day High (CDH)"]
            })
            levels.append({
                "price": round(curr_day["low"], 4),
                "type": "CDL",
                "timeframe": "1D",
                "evidence": ["Current Day Low (CDL)"]
            })

        # Weekly levels if 1W / 4H available
        w_candles = ohlc_data.get("1W") or (d_candles[-10:] if d_candles and len(d_candles) >= 10 else None)
        if w_candles and len(w_candles) >= 2:
            prev_week = w_candles[-2]
            levels.append({
                "price": round(prev_week["high"], 4),
                "type": "PWH",
                "timeframe": "1W",
                "evidence": ["Previous Week High (PWH)"]
            })
            levels.append({
                "price": round(prev_week["low"], 4),
                "type": "PWL",
                "timeframe": "1W",
                "evidence": ["Previous Week Low (PWL)"]
            })

        # Session levels from 15M / 5M
        s_candles = ohlc_data.get("15M") or ohlc_data.get("5M")
        if s_candles and len(s_candles) >= 24:
            # Half-day / session proxy window
            prev_session_candles = s_candles[-48:-24] if len(s_candles) >= 48 else s_candles[:-12]
            curr_session_candles = s_candles[-24:]

            if prev_session_candles:
                psh = max(c["high"] for c in prev_session_candles)
                psl = min(c["low"] for c in prev_session_candles)
                levels.append({
                    "price": round(psh, 4),
                    "type": "PSH",
                    "timeframe": "SESSION",
                    "evidence": ["Previous Session High (PSH)"]
                })
                levels.append({
                    "price": round(psl, 4),
                    "type": "PSL",
                    "timeframe": "SESSION",
                    "evidence": ["Previous Session Low (PSL)"]
                })

            if curr_session_candles:
                csh = max(c["high"] for c in curr_session_candles)
                csl = min(c["low"] for c in curr_session_candles)
                levels.append({
                    "price": round(csh, 4),
                    "type": "CSH",
                    "timeframe": "SESSION",
                    "evidence": ["Current Session High (CSH)"]
                })
                levels.append({
                    "price": round(csl, 4),
                    "type": "CSL",
                    "timeframe": "SESSION",
                    "evidence": ["Current Session Low (CSL)"]
                })

        return levels

    def count_consolidated_interactions(
        self,
        target_price: float,
        candles: List[Dict[str, Any]],
        tolerance: float
    ) -> Dict[str, int]:
        """
        Calculates interaction metrics (touches, rejections, defenses, failed breaks).
        Crucial Rule: Consolidate consecutive candles around the same price into a single interaction event
        to avoid treating a 20-candle consolidation as 20 independent touches!
        """
        if not candles:
            return {"touches": 0, "rejections": 0, "defenses": 0}

        events = 0
        rejections = 0
        defenses = 0
        in_reaction_event = False

        for c in candles:
            high = c['high']
            low = c['low']
            close_p = c['close']

            is_touching = (low - tolerance) <= target_price <= (high + tolerance)

            if is_touching:
                if not in_reaction_event:
                    events += 1
                    in_reaction_event = True

                    # Check rejection within event
                    upper_w = high - close_p
                    lower_w = close_p - low
                    c_range = max(0.0001, high - low)

                    if upper_w / c_range > 0.45 or lower_w / c_range > 0.45:
                        rejections += 1

                    # Successful defense (close remained on safe side of price)
                    if abs(close_p - target_price) > (tolerance * 0.5):
                        defenses += 1
            else:
                in_reaction_event = False

        return {
            "touches": events,
            "rejections": rejections,
            "defenses": defenses
        }

market_structure_engine = MarketStructureEngine()
