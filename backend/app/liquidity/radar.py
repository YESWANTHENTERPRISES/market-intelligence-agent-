from typing import Dict, List, Any, Optional

class LiquidityRadar:
    def analyze_liquidity_pools(
        self,
        equal_levels: List[Dict[str, Any]],
        dom_intelligence: Any,
        current_price: float
    ) -> List[Dict[str, Any]]:
        """
        Analyzes buy-side and sell-side liquidity pools using equal highs/lows,
        DOM bid/ask depth concentration, and retail positioning bias.
        """
        candidates = []

        # 1. Process Equal Highs / Equal Lows
        for eq in equal_levels:
            cand_type = eq.get("type")
            if cand_type == "EQUAL_HIGH":
                candidates.append({
                    "price": eq["price"],
                    "source": "EQUAL_HIGHS",
                    "timeframe": eq.get("timeframe", "1H"),
                    "type": "BUY_SIDE_LIQUIDITY",
                    "strength": 0.85,
                    "evidence": eq.get("evidence", ["Equal highs liquidity pool"]),
                    "liquidity": {"type": "BUY_SIDE", "strength": "HIGH"}
                })
            elif cand_type == "EQUAL_LOW":
                candidates.append({
                    "price": eq["price"],
                    "source": "EQUAL_LOWS",
                    "timeframe": eq.get("timeframe", "1H"),
                    "type": "SELL_SIDE_LIQUIDITY",
                    "strength": 0.85,
                    "evidence": eq.get("evidence", ["Equal lows liquidity pool"]),
                    "liquidity": {"type": "SELL_SIDE", "strength": "HIGH"}
                })

        # 2. Process DOM Liquidity Zones
        if dom_intelligence and hasattr(dom_intelligence, "liquidity"):
            retail_bias = getattr(dom_intelligence, "retail_positioning", "UNAVAILABLE")

            for zone in dom_intelligence.liquidity:
                # Parse range midpoint
                pr_str = zone.price_range if hasattr(zone, "price_range") else zone.get("price_range", "")
                side = zone.side if hasattr(zone, "side") else zone.get("side", "")
                score = zone.score if hasattr(zone, "score") else zone.get("score", 50.0)

                if "–" in pr_str:
                    try:
                        parts = pr_str.split("–")
                        p_mid = round((float(parts[0]) + float(parts[1])) / 2.0, 4)
                    except ValueError:
                        continue
                else:
                    try:
                        p_mid = float(pr_str)
                    except ValueError:
                        continue

                if "ASK" in side or "SELL" in side:
                    ev = ["DOM ask concentration (Futures & Spot)"]
                    if retail_bias == "SHORT":
                        ev.append("OANDA/OTC retail short positioning overhead")

                    candidates.append({
                        "price": p_mid,
                        "source": "DOM_ENGINE",
                        "timeframe": "REALTIME",
                        "type": "ASK_LIQUIDITY",
                        "strength": min(0.95, score / 100.0),
                        "evidence": ev,
                        "liquidity": {"type": "BUY_SIDE", "strength": "HIGH" if score > 60 else "MODERATE"}
                    })

                elif "BID" in side or "BUY" in side:
                    ev = ["DOM bid concentration (Futures & Spot)"]
                    if retail_bias == "LONG":
                        ev.append("OANDA/OTC retail long positioning beneath")

                    candidates.append({
                        "price": p_mid,
                        "source": "DOM_ENGINE",
                        "timeframe": "REALTIME",
                        "type": "BID_LIQUIDITY",
                        "strength": min(0.95, score / 100.0),
                        "evidence": ev,
                        "liquidity": {"type": "SELL_SIDE", "strength": "HIGH" if score > 60 else "MODERATE"}
                    })

        return candidates

liquidity_radar = LiquidityRadar()
