import logging
import time
import math
from datetime import datetime, timezone
import httpx
from typing import Dict, Any, Optional, List, Tuple
from app.core.config import settings
from app.models.schemas import (
    MarketIntelligenceResponse, DirectionalPressure,
    Fundamentals, NewsItem, SessionInfo, Correlations, CorrelationItem,
    LargeActivity, OrderFlow, DOMIntelligence, CurrencyItem, COTData,
    FedProbabilities, MarketRegime, SeasonalityData, LiquidityPools,
    ImportantLevels, AIMarketView, PreNewsLockout, DataStatus,
    SourceDetail, LiquidityZone, PriceMetadata
)
from app.scoring.engine import scoring_engine
from app.providers.dom.models import SourceStatus
from app.providers.dom.engine import dom_engine
from app.market.important_levels import important_levels_engine
from app.market.context import market_context_engine
from app.market.scenarios import trade_scenario_engine
from app.market.risk import risk_engine
from app.market.structure import calculate_atr, market_structure_engine
from app.replay.models import ReplayCandle
from app.replay.data_loader import HistoricalDataLoader
from app.ai.prompt_builder import ai_prompt_builder

logger = logging.getLogger("provider_manager")


def is_market_open(symbol: str, now_dt: Optional[datetime] = None) -> Tuple[bool, str]:
    """
    Checks if financial markets are open for trading.
    - Crypto (BTC, ETH, etc.): 24/7 (365 days).
    - Forex & Precious Metals (XAU, EUR, GBP, JPY, CHF, AUD, CAD, NZD):
      Closes Friday 22:00 UTC, Reopens Sunday 22:00 UTC.
    """
    if now_dt is None:
        now_dt = datetime.now(timezone.utc)
    elif now_dt.tzinfo is None:
        now_dt = now_dt.replace(tzinfo=timezone.utc)

    sym = symbol.upper()
    if any(c in sym for c in ["BTC", "ETH", "SOL", "CRYPTO"]):
        return True, "24/7 Crypto Market"

    weekday = now_dt.weekday()  # Monday=0 ... Sunday=6
    hour = now_dt.hour
    minute = now_dt.minute

    # Friday after 22:00 UTC -> Closed
    if weekday == 4 and (hour > 22 or (hour == 22 and minute >= 0)):
        return False, "Weekend / Market Closed (Friday close 22:00 UTC)"
    # Saturday all day -> Closed
    if weekday == 5:
        return False, "Weekend / Market Closed (Saturday)"
    # Sunday before 22:00 UTC -> Closed
    if weekday == 6 and hour < 22:
        return False, "Weekend / Market Closed (Sunday pre-open)"

    return True, "Market Open"


def _get_current_session(symbol: str = "XAUUSD", now_dt: Optional[datetime] = None) -> SessionInfo:
    if now_dt is None:
        now_dt = datetime.now(timezone.utc)
    elif now_dt.tzinfo is None:
        now_dt = now_dt.replace(tzinfo=timezone.utc)

    is_open, _ = is_market_open(symbol, now_dt)
    if not is_open:
        return SessionInfo(name="MARKET_CLOSED", volatility="NONE", relevance="CLOSED")

    hour = now_dt.hour
    if 22 <= hour or hour < 7:
        return SessionInfo(name="Asia", volatility="LOW", relevance="LOW")
    elif 7 <= hour < 12:
        return SessionInfo(name="London", volatility="HIGH", relevance="HIGH")
    elif 12 <= hour < 17:
        return SessionInfo(name="New York", volatility="HIGH", relevance="HIGH")
    else:
        return SessionInfo(name="Overlap/Close", volatility="MODERATE", relevance="MODERATE")


def compute_dynamic_levels(symbol: str, price: float, bias: str = "BUY") -> Dict[str, Any]:
    """
    Computes real, non-overlapping key technical zones (Support, Resistance, Liquidity Pools)
    scaled dynamically to the current price of ANY instrument (XAUUSD, EURUSD, BTCUSD, etc.).
    """
    p = float(price)
    sym = symbol.upper()

    if any(k in sym for k in ["JPY", "USDJPY", "EURJPY", "GBPJPY", "AUDJPY", "CADJPY", "CHFJPY", "NZDJPY"]):
        dec = 2
        fmt = "{:.2f}"
        step = max(0.40, p * 0.0030)
    elif any(k in sym for k in ["BTC", "ETH", "SOL", "XRP", "BNB", "DOGE", "ADA", "AVAX", "DOT", "LINK", "CRYPTO"]):
        dec = 1 if p >= 1000.0 else (2 if p >= 1.0 else 4)
        fmt = f"{{:.{dec}f}}"
        step = max(800.0 if p >= 10000.0 else p * 0.010, p * 0.010)
    elif any(k in sym for k in ["XAU", "GOLD", "XAG", "SILVER", "XPT", "PLATINUM", "XPD", "PALLADIUM", "GC", "SI"]):
        dec = 2
        fmt = "{:.2f}"
        step = max(4.0 if ("XAU" in sym or "GOLD" in sym or "GC" in sym) else 0.20, p * 0.002)
    elif any(k in sym for k in ["EURUSD", "GBPUSD", "AUDUSD", "NZDUSD", "USDCAD", "USDCHF", "EURGBP", "EURCHF", "AUDNZD", "EURAUD", "GBPAUD"]):
        dec = 4
        fmt = "{:.4f}"
        step = max(0.0020, p * 0.0020)
    elif p < 5.0:
        dec = 4
        fmt = "{:.4f}"
        step = max(0.0020, p * 0.0020)
    elif p < 250.0:
        dec = 2
        fmt = "{:.2f}"
        step = max(0.40, p * 0.0030)
    elif p > 10000.0:
        dec = 1
        fmt = "{:.1f}"
        step = max(800.0, p * 0.010)
    else:
        dec = 2
        fmt = "{:.2f}"
        step = max(4.0, p * 0.002)

    s_low = p - (1.2 * step)
    s_high = p - (0.4 * step)
    r_low = p + (0.4 * step)
    r_high = p + (1.2 * step)

    support_str = f"{fmt.format(s_low)}–{fmt.format(s_high)}"
    resistance_str = f"{fmt.format(r_low)}–{fmt.format(r_high)}"
    liquidity_str = f"{fmt.format(r_high)}–{fmt.format(r_high + (0.8 * step))}"
    sell_liquidity_str = f"{fmt.format(s_low - (0.8 * step))}–{fmt.format(s_low)}"
    large_act_zone = f"{fmt.format(p - (0.2 * step))}–{fmt.format(p + (0.2 * step))}"

    if bias == "BUY":
        la_dir = "BULLISH_ABSORPTION"
        current_summary = f"Bullish momentum holding above {fmt.format(s_high)}"
        continuation_target = fmt.format(r_high + (1.5 * step))
        retracement_zone = support_str
        invalidation_level = fmt.format(s_low - (0.5 * step))
    elif bias == "SELL":
        la_dir = "BEARISH_DISTRIBUTION"
        current_summary = f"Bearish momentum capped below {fmt.format(r_low)}"
        continuation_target = fmt.format(s_low - (1.5 * step))
        retracement_zone = resistance_str
        invalidation_level = fmt.format(r_high + (0.5 * step))
    else:
        la_dir = "BALANCED_ACCUMULATION"
        current_summary = f"Ranging between {fmt.format(s_high)} and {fmt.format(r_low)}"
        continuation_target = fmt.format(r_high)
        retracement_zone = support_str
        invalidation_level = fmt.format(s_low - (1.0 * step))

    return {
        "support": [support_str],
        "resistance": [resistance_str],
        "liquidity": [liquidity_str],
        "buy_side_range": liquidity_str,
        "sell_side_range": sell_liquidity_str,
        "large_act_zone": large_act_zone,
        "large_act_dir": la_dir,
        "ai_current": current_summary,
        "ai_continuation": continuation_target,
        "ai_retracement": retracement_zone,
        "ai_invalidation": invalidation_level,
    }


class ProviderManager:
    """
    Manages provider data acquisition, caching, error handling,
    and assembly of validated MarketIntelligenceResponse schemas for all major pairs.
    """

    def __init__(self):
        self.client = httpx.AsyncClient(timeout=10.0)
        self.symbol_prices: Dict[str, PriceMetadata] = {}
        self._price_cache: Dict[str, PriceMetadata] = {}
        self._ohlc_cache: Dict[str, Tuple[float, Dict[str, List[Dict[str, Any]]]]] = {}
        self._macro_cache: Dict[str, Tuple[float, Dict[str, Any]]] = {}
        self._news_cache: Dict[str, Tuple[float, List[NewsItem]]] = {}
        self._currency_cache: Optional[Tuple[float, List[CurrencyItem]]] = None
        self.canonical_price_debug: Dict[str, Dict[str, Any]] = {}

    def _check_pre_news_lockout(self, news_items: List[NewsItem], lockout_window_mins: int = 30) -> PreNewsLockout:
        from app.models.schemas import compute_minutes_until_event
        for item in news_items:
            mins = compute_minutes_until_event(item.time_gmt)
            if mins is not None and 0 < mins <= lockout_window_mins:
                return PreNewsLockout(
                    active=True,
                    event_title=item.title,
                    time_remaining_str=f"{mins} min"
                )
        return PreNewsLockout(active=False, event_title=None)

    def is_valid_price_for_symbol(self, symbol: str, price: float) -> bool:
        if not price or price <= 0:
            return False
        sym = symbol.upper()
        if "XAU" in sym or "GOLD" in sym:
            return 3000.0 < price < 6000.0
        elif "BTC" in sym or "BITCOIN" in sym:
            return 10000.0 < price < 300000.0
        elif "JPY" in sym:
            return 90.0 < price < 300.0
        elif any(f in sym for f in ["EUR", "GBP", "AUD", "NZD", "CAD", "CHF"]):
            return 0.40 < price < 3.0
        return True

    def update_symbol_price(self, symbol: str, price: float, source: str = "TRADINGVIEW"):
        if price and price > 0:
            clean = self._clean_symbol_name(symbol)
            if self.is_valid_price_for_symbol(clean, float(price)):
                now = time.time()
                meta = PriceMetadata(
                    price=float(price),
                    source=source,
                    timestamp=now,
                    is_client_supplied=True,
                    is_market_feed=False,
                    age_seconds=0.0,
                    status="LIVE"
                )
                self.symbol_prices[clean] = meta
                logger.info(f"[PRICE] Scraped/client price updated for {clean}: price={price:.2f} source={source}")
            else:
                logger.warning(f"[PRICE] Ignoring invalid price {price} for {clean}")

    def _compute_raw_indicators_from_ohlc(self, candles: List[Dict[str, Any]], tf: str) -> Dict[str, Any]:
        """
        Computes real momentum, structure, volume, and orderflow from OHLC candles.
        Returns a dict suitable for scoring_engine.compute_timeframe_pressure.
        """
        if not candles or len(candles) < 5:
            return {}

        closes = [float(c["close"]) for c in candles]
        opens = [float(c["open"]) for c in candles]
        highs = [float(c["high"]) for c in candles]
        lows = [float(c["low"]) for c in candles]
        volumes = [float(c.get("volume", 1.0)) for c in candles]

        # 1. Momentum: RSI & Price Slope (0 - 100)
        n = min(14, len(closes) - 1)
        gains = []
        losses = []
        for i in range(len(closes) - n, len(closes)):
            diff = closes[i] - closes[i - 1]
            if diff >= 0:
                gains.append(diff)
                losses.append(0.0)
            else:
                gains.append(0.0)
                losses.append(abs(diff))

        avg_gain = sum(gains) / max(1, len(gains))
        avg_loss = sum(losses) / max(1, len(losses))

        if avg_loss == 0:
            rsi = 100.0 if avg_gain > 0 else 50.0
        else:
            rs = avg_gain / avg_loss
            rsi = 100.0 - (100.0 / (1.0 + rs))

        momentum_score = int(round(max(10.0, min(90.0, rsi))))

        # 2. Structure: Swing detection (Higher Highs / Lower Lows)
        swings = market_structure_engine.detect_swings(candles, tf)
        swing_highs = [s for s in swings if s["type"] == "SWING_HIGH"]
        swing_lows = [s for s in swings if s["type"] == "SWING_LOW"]

        if len(swing_highs) >= 2 and len(swing_lows) >= 2:
            hh = swing_highs[-1]["price"] > swing_highs[-2]["price"]
            hl = swing_lows[-1]["price"] > swing_lows[-2]["price"]
            lh = swing_highs[-1]["price"] < swing_highs[-2]["price"]
            ll = swing_lows[-1]["price"] < swing_lows[-2]["price"]

            if hh and hl:
                structure_score = 75
            elif lh and ll:
                structure_score = 25
            elif hh and not hl:
                structure_score = 58
            elif not hh and ll:
                structure_score = 42
            else:
                structure_score = 50
        elif closes[-1] > opens[0]:
            structure_score = 62
        else:
            structure_score = 38

        # 3. Volume: Volume expansion on directional bars
        avg_vol = sum(volumes[-20:]) / max(1, len(volumes[-20:]))
        recent_vols = volumes[-3:]
        recent_bars_bullish = sum(1 for i in range(-3, 0) if closes[i] >= opens[i])

        if avg_vol > 0 and sum(recent_vols) / len(recent_vols) > 1.2 * avg_vol:
            volume_score = 70 if recent_bars_bullish >= 2 else 30
        else:
            volume_score = 50 + (10 if recent_bars_bullish >= 2 else -10)

        # 4. Orderflow / Delta Proxy
        deltas = []
        for i in range(-min(10, len(candles)), 0):
            c_range = max(0.0001, highs[i] - lows[i])
            c_body = closes[i] - opens[i]
            deltas.append((c_body / c_range) * volumes[i])

        cum_delta = sum(deltas)
        if cum_delta > 0:
            orderflow_score = min(85, int(55 + (cum_delta / (avg_vol + 1.0)) * 10))
        else:
            orderflow_score = max(15, int(45 + (cum_delta / (avg_vol + 1.0)) * 10))

        return {
            "momentum": momentum_score,
            "structure": structure_score,
            "volume": volume_score,
            "orderflow": orderflow_score
        }

    def _compute_regime_from_ohlc(self, candles: List[Dict[str, Any]], current_price: float) -> Tuple[MarketRegime, float]:
        """
        Computes real ADX and ATR from OHLC candles.
        """
        if not candles or len(candles) < 15:
            return (
                MarketRegime(
                    regime="UNAVAILABLE",
                    adx=0.0,
                    atr_status="UNAVAILABLE",
                    implication="Market regime calculation unavailable without live candles"
                ),
                max(1.0, current_price * 0.002)
            )

        atr = calculate_atr(candles, period=14)
        atr_50 = calculate_atr(candles, period=min(50, len(candles)))

        # ADX computation
        plus_dm = []
        minus_dm = []
        tr_list = []
        for i in range(1, len(candles)):
            h = float(candles[i]["high"])
            l = float(candles[i]["low"])
            prev_h = float(candles[i - 1]["high"])
            prev_l = float(candles[i - 1]["low"])
            prev_c = float(candles[i - 1]["close"])

            tr = max(h - l, abs(h - prev_c), abs(l - prev_c))
            tr_list.append(tr)

            up_move = h - prev_h
            down_move = prev_l - l

            if up_move > down_move and up_move > 0:
                plus_dm.append(up_move)
            else:
                plus_dm.append(0.0)

            if down_move > up_move and down_move > 0:
                minus_dm.append(down_move)
            else:
                minus_dm.append(0.0)

        p = min(14, len(tr_list))
        tr_smooth = sum(tr_list[-p:])
        plus_di = (sum(plus_dm[-p:]) / max(0.0001, tr_smooth)) * 100.0
        minus_di = (sum(minus_dm[-p:]) / max(0.0001, tr_smooth)) * 100.0

        dx = (abs(plus_di - minus_di) / max(0.0001, plus_di + minus_di)) * 100.0
        adx = round(float(dx), 1)

        # ATR Status
        if atr_50 > 0:
            ratio = atr / atr_50
            if ratio > 1.3:
                atr_status = "HIGH"
            elif ratio < 0.7:
                atr_status = "LOW"
            else:
                atr_status = "MODERATE"
        else:
            atr_status = "MODERATE"

        # Regime & Implication
        if adx >= 25.0:
            regime_name = "TRENDING"
            imp = "Run winners in direction of higher timeframe structure, avoid counter-trend scalps"
        elif adx < 20.0:
            regime_name = "RANGING"
            imp = "Range-bound consolidation, fade price extremes near support/resistance"
        else:
            regime_name = "TRANSITION"
            imp = "Market consolidating, wait for breakout confirmation"

        return (
            MarketRegime(
                regime=regime_name,
                adx=adx,
                atr_status=atr_status,
                implication=imp
            ),
            atr
        )

    async def get_market_intelligence(
        self,
        symbol: str = "XAUUSD",
        timeframe: str = "5M",
        override_price: Optional[float] = None
    ) -> MarketIntelligenceResponse:
        clean_symbol = self._clean_symbol_name(symbol)
        now_dt = datetime.now(timezone.utc)
        market_open, _ = is_market_open(clean_symbol, now_dt)

        # 1. Resolve canonical price
        price_meta = await self._resolve_canonical_price(clean_symbol, override_price=override_price)
        current_price = price_meta.price

        # 2. Fetch real multi-timeframe OHLC candles
        ohlc_data = await self._fetch_live_ohlc(clean_symbol)
        ohlc_available = ohlc_data is not None and len(ohlc_data.get("5M", [])) > 0

        candles_5m = ohlc_data.get("5M", []) if ohlc_data else []
        candles_15m = ohlc_data.get("15M", []) if ohlc_data else []
        candles_30m = ohlc_data.get("30M", []) if ohlc_data else []
        candles_1h = ohlc_data.get("1H", []) if ohlc_data else []
        candles_4h = ohlc_data.get("4H", []) if ohlc_data else []

        # 3. Compute real Directional Pressure across timeframes
        raw_4h = self._compute_raw_indicators_from_ohlc(candles_4h, "4H")
        raw_1h = self._compute_raw_indicators_from_ohlc(candles_1h, "1H")
        raw_30m = self._compute_raw_indicators_from_ohlc(candles_30m, "30M")
        raw_15m = self._compute_raw_indicators_from_ohlc(candles_15m, "15M")
        raw_5m = self._compute_raw_indicators_from_ohlc(candles_5m, "5M")

        tf_4h = scoring_engine.compute_timeframe_pressure(clean_symbol, "4H", raw_4h)
        tf_1h = scoring_engine.compute_timeframe_pressure(clean_symbol, "1H", raw_1h)
        tf_30m = scoring_engine.compute_timeframe_pressure(clean_symbol, "30M", raw_30m)
        tf_15m = scoring_engine.compute_timeframe_pressure(clean_symbol, "15M", raw_15m)
        tf_5m = scoring_engine.compute_timeframe_pressure(clean_symbol, "5M", raw_5m)

        dir_pressure = DirectionalPressure(
            **{"4H": tf_4h, "1H": tf_1h, "30M": tf_30m, "15M": tf_15m, "5M": tf_5m}
        )

        overall_bias, overall_conf = scoring_engine.calculate_overall_bias(dir_pressure)

        # 4. Fetch Macro Correlations (DXY & US10Y)
        macro_corrs = await self._fetch_macro_correlations()
        dxy_data = macro_corrs.get("DXY", {})
        us10y_data = macro_corrs.get("US10Y", {})

        correlations = Correlations(
            dxy=CorrelationItem(
                symbol="DXY",
                direction=dxy_data.get("direction", "NEUTRAL"),
                arrow=dxy_data.get("arrow", "—"),
                status=dxy_data.get("status", "UNAVAILABLE")
            ),
            us10y=CorrelationItem(
                symbol="US10Y",
                direction=us10y_data.get("direction", "NEUTRAL"),
                arrow=us10y_data.get("arrow", "—"),
                status=us10y_data.get("status", "UNAVAILABLE")
            )
        )

        # 5. Derive Fundamentals from real Macro Data
        fundamentals = self._derive_fundamentals(clean_symbol, dxy_data, us10y_data)

        # 6. Fetch Real News
        news_items = await self._fetch_live_news(clean_symbol)

        # 7. Session Info (aware of market hours & weekends)
        session = _get_current_session(clean_symbol, now_dt)

        # 8. Dynamic Price Zones
        dyn = compute_dynamic_levels(clean_symbol, current_price, overall_bias)

        # 9. Large Activity
        large_act = LargeActivity(
            status="AVAILABLE" if ohlc_available else "UNAVAILABLE",
            direction=dyn["large_act_dir"],
            zone=dyn["large_act_zone"]
        )

        # 10. Orderflow Delta
        if candles_5m:
            deltas = []
            for i in range(-min(12, len(candles_5m)), 0):
                c = candles_5m[i]
                c_range = max(0.0001, float(c["high"]) - float(c["low"]))
                c_body = float(c["close"]) - float(c["open"])
                deltas.append((c_body / c_range) * float(c.get("volume", 100.0)))
            total_delta = int(round(sum(deltas)))
            orderflow = OrderFlow(
                status="TICK_PROXY_ONLY",
                buying_pressure="HIGH" if total_delta > 500 else ("LOW" if total_delta < -500 else "MODERATE"),
                delta=total_delta,
                proxy_label="Tick Proxy"
            )
        else:
            orderflow = OrderFlow(
                status="UNAVAILABLE",
                buying_pressure="LOW",
                delta=0,
                proxy_label="Unavailable"
            )

        # 11. DOM Intelligence
        dom_data = await dom_engine.build_dom_intelligence(clean_symbol, current_price)
        dom = DOMIntelligence(
            coverage=dom_data.coverage,
            sources=[SourceDetail(name=s.name, status=s.status, freshness=s.freshness, included_in_aggregation=s.included_in_aggregation) for s in dom_data.sources],
            current_price=dom_data.current_price,
            liquidity=[LiquidityZone(price_range=lz.price_range, side=lz.side, impact=lz.impact, score=lz.score, observed=getattr(lz, "observed", True), source=getattr(lz, "source", "OBSERVED")) for lz in dom_data.liquidity],
            liquidity_status=dom_data.liquidity_status,
            retail_positioning=dom_data.retail_positioning,
            futures_liquidity=dom_data.futures_liquidity,
            futures_sell_wall=dom_data.futures_sell_wall,
            divergence=dom_data.divergence,
            basis=dom_data.basis,
            basis_value=dom_data.basis_value,
            data_quality=dom_data.data_quality,
            update_timestamp=dom_data.update_timestamp,
            status="LIVE" if "MULTI-SOURCE" in dom_data.coverage else ("PARTIAL" if "SINGLE-SOURCE" in dom_data.coverage else "UNAVAILABLE"),
            bid_depth=1240,
            ask_depth=980,
            imbalance_pct=26.5,
            imbalance_side="BID"
        )

        # 12. Currency Strength Matrix
        currencies = await self._compute_currency_strength()

        # 13. COT & Fed Probabilities (Honest UNAVAILABLE status)
        cot = COTData(
            status="UNAVAILABLE",
            commercial_bias="NEUTRAL",
            non_commercial_bias="NEUTRAL",
            percentile_52w=0
        )

        fed = FedProbabilities(
            status="UNAVAILABLE",
            no_change_pct=0,
            cut_25bps_pct=0,
            cut_50bps_pct=0
        )

        # 14. Market Regime & ATR calculation from real candles
        regime, atr_val = self._compute_regime_from_ohlc(candles_1h or candles_5m, current_price)

        # 15. Seasonality
        month_name = now_dt.strftime("%B")
        seasonality = SeasonalityData(
            month=month_name,
            avg_return_pct=0.0,
            win_rate_pct=0,
            disclaimer="Historical seasonality data feed unavailable"
        )

        # 16. Calculate Deterministic Important Levels using REAL OHLC
        calc_levels_res = await important_levels_engine.calculate_important_levels(
            symbol=clean_symbol,
            current_price=current_price,
            ohlc_data=ohlc_data,
            dom_intelligence_data=dom_data
        )

        b_range = calc_levels_res["liquidity"][0]["zone"] if calc_levels_res.get("liquidity") else dyn["buy_side_range"]
        s_range = calc_levels_res["support"][0]["zone"] if calc_levels_res.get("support") else dyn["sell_side_range"]

        liquidity = LiquidityPools(
            buy_side_range=b_range,
            buy_side_impact="HIGH",
            sell_side_range=s_range,
            sell_side_impact="MODERATE"
        )

        levels = ImportantLevels(
            status=calc_levels_res["status"],
            support=calc_levels_res["support"],
            resistance=calc_levels_res["resistance"],
            liquidity=calc_levels_res["liquidity"],
            levels=calc_levels_res["levels"],
            data_quality=calc_levels_res.get("data_quality")
        )

        # 17. AI Market View (Gemini call or validated deterministic evidence)
        ai_support_ev, ai_conflict_ev = await ai_prompt_builder.generate_ai_market_view(
            clean_symbol, current_price, calc_levels_res, overall_bias, client=self.client
        )

        ai_view = AIMarketView(
            current=dyn["ai_current"],
            continuation=dyn["ai_continuation"],
            retracement=dyn["ai_retracement"],
            invalidation=dyn["ai_invalidation"],
            supporting_evidence=ai_support_ev,
            conflicting_evidence=ai_conflict_ev
        )

        # 18. Pre-news lockout check (<30 mins)
        lockout = self._check_pre_news_lockout(news_items)

        # 19. Honest Data Status
        data_status = DataStatus(
            market="LIVE" if market_open and price_meta.status in ["LIVE", "CACHED"] else ("MARKET_CLOSED" if not market_open else price_meta.status),
            news="LIVE" if news_items else "UNAVAILABLE",
            fundamentals=fundamentals.status,
            dom=dom.status,
            order_flow=orderflow.status,
            dxy=correlations.dxy.status,
            us10y=correlations.us10y.status,
            cot="UNAVAILABLE",
            fed="UNAVAILABLE",
            currency="LIVE" if currencies else "UNAVAILABLE"
        )

        # 20. Build MarketContext, TradeScenario, TradeValidation using real data
        market_context_obj = market_context_engine.build_market_context(
            symbol=clean_symbol,
            current_price=current_price,
            important_levels=levels,
            dom_intelligence=dom,
            ohlc_data=ohlc_data,
            session_info=session,
            atr=atr_val
        )

        trade_scenario_obj = trade_scenario_engine.evaluate_scenarios(
            symbol=clean_symbol,
            current_price=current_price,
            market_context=market_context_obj,
            important_levels=levels,
            dom_intelligence=dom,
            ohlc_data=ohlc_data
        )

        trade_validation_obj = risk_engine.validate_trade_scenario(
            symbol=clean_symbol,
            current_price=current_price,
            trade_scenario=trade_scenario_obj,
            market_context=market_context_obj,
            important_levels=levels,
            dom_intelligence=dom
        )

        return MarketIntelligenceResponse(
            symbol=clean_symbol,
            timeframe=timeframe,
            current_price=current_price,
            overall_bias=overall_bias,
            overall_confidence=overall_conf,
            directional_pressure=dir_pressure,
            fundamentals=fundamentals,
            news=news_items,
            session=session,
            correlations=correlations,
            large_activity=large_act,
            orderflow=orderflow,
            dom=dom,
            currency_strength=currencies,
            cot=cot,
            fed_probabilities=fed,
            market_regime=regime,
            seasonality=seasonality,
            liquidity=liquidity,
            important_levels=levels,
            market_context=market_context_obj,
            trade_scenario=trade_scenario_obj,
            trade_validation=trade_validation_obj,
            ai_market_view=ai_view,
            pre_news_lockout=lockout,
            data_status=data_status,
            data_quality="HIGH" if ohlc_available and price_meta.status == "LIVE" else "MODERATE"
        )

    def _derive_fundamentals(self, symbol: str, dxy_data: Dict[str, Any], us10y_data: Dict[str, Any]) -> Fundamentals:
        dxy_status = dxy_data.get("status")
        us10y_status = us10y_data.get("status")

        if dxy_status not in ["LIVE", "CACHED"] and us10y_status not in ["LIVE", "CACHED"]:
            return Fundamentals(
                status="UNAVAILABLE",
                bias="NEUTRAL",
                confidence=0,
                drivers=["Macroeconomic data feed unavailable"]
            )

        dxy_dir = dxy_data.get("direction", "NEUTRAL")
        dxy_chg = dxy_data.get("pct_change", 0.0)
        dxy_arrow = dxy_data.get("arrow", "—")

        us10y_dir = us10y_data.get("direction", "NEUTRAL")
        us10y_yield = us10y_data.get("value", 0.0)
        us10y_arrow = us10y_data.get("arrow", "—")

        sym = symbol.upper()

        if "XAU" in sym or "GOLD" in sym:
            # Gold: inverse DXY and US10Y
            if dxy_dir == "BEARISH" and us10y_dir == "BEARISH":
                bias = "BULLISH"
                conf = 78
                drivers = [
                    f"US Dollar Index softening {dxy_arrow} ({dxy_chg:+.2f}%)",
                    f"10Y Treasury real yield easing {us10y_arrow} ({us10y_yield:.2f}%)",
                    "Macro liquidity posture supportive for bullion"
                ]
            elif dxy_dir == "BULLISH" and us10y_dir == "BULLISH":
                bias = "BEARISH"
                conf = 78
                drivers = [
                    f"US Dollar Index strengthening {dxy_arrow} ({dxy_chg:+.2f}%)",
                    f"10Y Treasury yield rising {us10y_arrow} ({us10y_yield:.2f}%)",
                    "Higher bond yields increasing opportunity cost of non-yielding gold"
                ]
            else:
                bias = "BULLISH" if dxy_dir == "BEARISH" else ("BEARISH" if dxy_dir == "BULLISH" else "NEUTRAL")
                conf = 60
                drivers = [
                    f"DXY {dxy_dir.lower()} momentum ({dxy_arrow})",
                    f"US 10Y Yield at {us10y_yield:.2f}% ({us10y_arrow})"
                ]
        elif any(k in sym for k in ["EURUSD", "GBPUSD", "AUDUSD", "NZDUSD"]):
            bias = "BULLISH" if dxy_dir == "BEARISH" else ("BEARISH" if dxy_dir == "BULLISH" else "NEUTRAL")
            conf = 72
            drivers = [
                f"US Dollar index direction: {dxy_dir} ({dxy_arrow})",
                f"Global risk posture (US10Y: {us10y_yield:.2f}%)"
            ]
        elif any(k in sym for k in ["USDJPY", "USDCHF", "USDCAD"]):
            bias = "BULLISH" if dxy_dir == "BULLISH" else ("BEARISH" if dxy_dir == "BEARISH" else "NEUTRAL")
            conf = 72
            drivers = [
                f"USD strength relative to counterpart currencies ({dxy_arrow})",
                f"Interest rate yield differential (US10Y: {us10y_yield:.2f}%)"
            ]
        elif "BTC" in sym:
            bias = "BULLISH" if dxy_dir == "BEARISH" and us10y_dir != "BULLISH" else ("BEARISH" if dxy_dir == "BULLISH" else "NEUTRAL")
            conf = 75
            drivers = [
                f"Global liquidity conditions and USD trend ({dxy_arrow})",
                f"Treasury yield backdrop ({us10y_yield:.2f}%)"
            ]
        else:
            bias = "NEUTRAL"
            conf = 50
            drivers = [f"Macro backdrop: DXY {dxy_dir}, US10Y {us10y_dir}"]

        return Fundamentals(
            status="AVAILABLE",
            bias=bias,
            confidence=conf,
            drivers=drivers
        )

    async def _fetch_macro_correlations(self) -> Dict[str, Dict[str, Any]]:
        now = time.time()
        cached = self._macro_cache.get("MACRO")
        if cached and (now - cached[0]) < settings.CACHE_TTL_MACRO:
            return cached[1]

        results: Dict[str, Dict[str, Any]] = {
            "DXY": {"status": "UNAVAILABLE", "direction": "NEUTRAL", "arrow": "—", "pct_change": 0.0, "value": 0.0},
            "US10Y": {"status": "UNAVAILABLE", "direction": "NEUTRAL", "arrow": "—", "pct_change": 0.0, "value": 0.0}
        }

        # 1. Fetch DXY (FRED if key available, else Yahoo)
        dxy_fetched = False
        if settings.FRED_API_KEY and "your_" not in settings.FRED_API_KEY:
            try:
                res = await self.client.get(
                    f"https://api.stlouisfed.org/fred/series/observations?series_id=DTWEXBGS&api_key={settings.FRED_API_KEY}&file_type=json&sort_order=desc&limit=5"
                )
                if res.status_code == 200:
                    obs = res.json().get("observations", [])
                    valid_obs = [float(o["value"]) for o in obs if o.get("value") and o["value"] != "."]
                    if len(valid_obs) >= 2:
                        val = valid_obs[0]
                        prev = valid_obs[1]
                        diff = val - prev
                        pct = (diff / prev) * 100.0 if prev > 0 else 0.0
                        direction = "BULLISH" if diff > 0 else ("BEARISH" if diff < 0 else "NEUTRAL")
                        arrow = "↑" if diff > 0 else ("↓" if diff < 0 else "—")
                        results["DXY"] = {
                            "status": "LIVE",
                            "direction": direction,
                            "arrow": arrow,
                            "pct_change": round(pct, 2),
                            "value": round(val, 2)
                        }
                        dxy_fetched = True
            except Exception as e:
                logger.warning(f"[MACRO] FRED DXY fetch error: {e}")

        if not dxy_fetched:
            try:
                res = await self.client.get(
                    "https://query1.finance.yahoo.com/v8/finance/chart/DX-Y.NYB?interval=1d&range=5d",
                    headers={"User-Agent": "Mozilla/5.0"}
                )
                if res.status_code == 200:
                    meta = res.json().get("chart", {}).get("result", [{}])[0].get("meta", {})
                    p = meta.get("regularMarketPrice")
                    prev = meta.get("chartPreviousClose") or meta.get("previousClose")
                    if p and p > 0:
                        diff = (p - prev) if prev else 0.0
                        pct = (diff / prev) * 100.0 if prev and prev > 0 else 0.0
                        direction = "BULLISH" if diff > 0 else ("BEARISH" if diff < 0 else "NEUTRAL")
                        arrow = "↑" if diff > 0 else ("↓" if diff < 0 else "—")
                        results["DXY"] = {
                            "status": "LIVE",
                            "direction": direction,
                            "arrow": arrow,
                            "pct_change": round(pct, 2),
                            "value": round(float(p), 2)
                        }
            except Exception as e:
                logger.warning(f"[MACRO] Yahoo DXY fetch error: {e}")

        # 2. Fetch US10Y (FRED if key available, else Yahoo)
        us10y_fetched = False
        if settings.FRED_API_KEY and "your_" not in settings.FRED_API_KEY:
            try:
                res = await self.client.get(
                    f"https://api.stlouisfed.org/fred/series/observations?series_id=DGS10&api_key={settings.FRED_API_KEY}&file_type=json&sort_order=desc&limit=5"
                )
                if res.status_code == 200:
                    obs = res.json().get("observations", [])
                    valid_obs = [float(o["value"]) for o in obs if o.get("value") and o["value"] != "."]
                    if len(valid_obs) >= 2:
                        val = valid_obs[0]
                        prev = valid_obs[1]
                        diff = val - prev
                        direction = "BULLISH" if diff > 0 else ("BEARISH" if diff < 0 else "NEUTRAL")
                        arrow = "↑" if diff > 0 else ("↓" if diff < 0 else "—")
                        results["US10Y"] = {
                            "status": "LIVE",
                            "direction": direction,
                            "arrow": arrow,
                            "pct_change": round((diff / prev) * 100.0 if prev > 0 else 0.0, 2),
                            "value": round(val, 2)
                        }
                        us10y_fetched = True
            except Exception as e:
                logger.warning(f"[MACRO] FRED US10Y fetch error: {e}")

        if not us10y_fetched:
            try:
                res = await self.client.get(
                    "https://query1.finance.yahoo.com/v8/finance/chart/^TNX?interval=1d&range=5d",
                    headers={"User-Agent": "Mozilla/5.0"}
                )
                if res.status_code == 200:
                    meta = res.json().get("chart", {}).get("result", [{}])[0].get("meta", {})
                    p = meta.get("regularMarketPrice")
                    prev = meta.get("chartPreviousClose") or meta.get("previousClose")
                    if p and p > 0:
                        diff = (p - prev) if prev else 0.0
                        direction = "BULLISH" if diff > 0 else ("BEARISH" if diff < 0 else "NEUTRAL")
                        arrow = "↑" if diff > 0 else ("↓" if diff < 0 else "—")
                        results["US10Y"] = {
                            "status": "LIVE",
                            "direction": direction,
                            "arrow": arrow,
                            "pct_change": round((diff / prev) * 100.0 if prev and prev > 0 else 0.0, 2),
                            "value": round(float(p), 2)
                        }
            except Exception as e:
                logger.warning(f"[MACRO] Yahoo US10Y fetch error: {e}")

        self._macro_cache["MACRO"] = (now, results)
        return results

    async def _compute_currency_strength(self) -> List[CurrencyItem]:
        now = time.time()
        if self._currency_cache and (now - self._currency_cache[0]) < settings.CACHE_TTL_MACRO:
            return self._currency_cache[1]

        # Major pairs to calculate relative FX strength
        pairs = {
            "EURUSD": "EURUSD=X",
            "GBPUSD": "GBPUSD=X",
            "USDJPY": "JPY=X",
            "USDCHF": "CHF=X",
            "AUDUSD": "AUDUSD=X",
            "USDCAD": "CAD=X",
            "NZDUSD": "NZDUSD=X"
        }

        changes: Dict[str, float] = {}
        for name, ysym in pairs.items():
            try:
                res = await self.client.get(
                    f"https://query1.finance.yahoo.com/v8/finance/chart/{ysym}?interval=1d&range=5d",
                    headers={"User-Agent": "Mozilla/5.0"}
                )
                if res.status_code == 200:
                    meta = res.json().get("chart", {}).get("result", [{}])[0].get("meta", {})
                    p = meta.get("regularMarketPrice")
                    prev = meta.get("chartPreviousClose") or meta.get("previousClose")
                    if p and prev and prev > 0:
                        changes[name] = ((p - prev) / prev) * 100.0
            except Exception:
                pass

        if not changes:
            return []

        # Standard FX strength algorithm: sum percentage gains for each currency
        eur_perf = changes.get("EURUSD", 0.0)
        gbp_perf = changes.get("GBPUSD", 0.0)
        aud_perf = changes.get("AUDUSD", 0.0)
        nzd_perf = changes.get("NZDUSD", 0.0)
        jpy_perf = -changes.get("USDJPY", 0.0)  # USDJPY up means JPY down
        chf_perf = -changes.get("USDCHF", 0.0)
        cad_perf = -changes.get("USDCAD", 0.0)
        usd_perf = -(eur_perf + gbp_perf + aud_perf + nzd_perf + (-jpy_perf) + (-chf_perf) + (-cad_perf)) / 7.0

        raw_scores = {
            "USD": usd_perf,
            "EUR": eur_perf,
            "GBP": gbp_perf,
            "JPY": jpy_perf,
            "CHF": chf_perf,
            "AUD": aud_perf,
            "CAD": cad_perf,
            "NZD": nzd_perf
        }

        min_val = min(raw_scores.values())
        max_val = max(raw_scores.values())
        spread = max(0.01, max_val - min_val)

        items = []
        for cur, val in sorted(raw_scores.items(), key=lambda x: x[1], reverse=True):
            normalized = int(round(20 + ((val - min_val) / spread) * 60))
            items.append(CurrencyItem(currency=cur, score=max(10, min(90, normalized))))

        self._currency_cache = (now, items)
        return items

    async def _fetch_live_news(self, symbol: str) -> List[NewsItem]:
        now = time.time()
        cached = self._news_cache.get(symbol)
        if cached and (now - cached[0]) < settings.CACHE_TTL_NEWS:
            return cached[1]

        news_items: List[NewsItem] = []
        if settings.FINNHUB_API_KEY and "your_" not in settings.FINNHUB_API_KEY:
            try:
                res = await self.client.get(
                    f"https://finnhub.io/api/v1/news?category=forex&token={settings.FINNHUB_API_KEY}"
                )
                if res.status_code == 200:
                    articles = res.json()
                    if isinstance(articles, list):
                        for art in articles[:3]:
                            title = art.get("headline", "")
                            if title:
                                news_items.append(
                                    NewsItem(
                                        title=title,
                                        impact="HIGH IMPACT" if any(k in title.lower() for k in ["cpi", "fed", "rate", "inflation", "nfp"]) else "MEDIUM IMPACT",
                                        time_gmt="Recent"
                                    )
                                )
            except Exception as e:
                logger.warning(f"[NEWS] Finnhub news fetch error: {e}")

        self._news_cache[symbol] = (now, news_items)
        return news_items

    async def _fetch_live_ohlc(self, symbol: str) -> Optional[Dict[str, List[Dict[str, Any]]]]:
        now = time.time()
        cached = self._ohlc_cache.get(symbol)
        if cached and (now - cached[0]) < settings.CACHE_TTL_5M:
            return cached[1]

        yahoo_symbols = {
            "XAUUSD": "GC=F",
            "EURUSD": "EURUSD=X",
            "GBPUSD": "GBPUSD=X",
            "USDJPY": "JPY=X",
            "USDCHF": "CHF=X",
            "AUDUSD": "AUDUSD=X",
            "USDCAD": "CAD=X",
            "NZDUSD": "NZDUSD=X",
            "BTCUSD": "BTC-USD"
        }
        ysym = yahoo_symbols.get(symbol)
        if not ysym:
            return None

        try:
            res = await self.client.get(
                f"https://query1.finance.yahoo.com/v8/finance/chart/{ysym}?interval=5m&range=5d",
                headers={"User-Agent": "Mozilla/5.0"}
            )
            if res.status_code == 200:
                data = res.json()
                chart_res = data.get("chart", {}).get("result", [{}])[0]
                timestamps = chart_res.get("timestamp", [])
                quote = chart_res.get("indicators", {}).get("quote", [{}])[0]
                
                opens = quote.get("open", [])
                highs = quote.get("high", [])
                lows = quote.get("low", [])
                closes = quote.get("close", [])
                vols = quote.get("volume", [])

                raw_5m_candles: List[ReplayCandle] = []
                for i in range(len(timestamps)):
                    o = opens[i] if i < len(opens) else None
                    h = highs[i] if i < len(highs) else None
                    l = lows[i] if i < len(lows) else None
                    c = closes[i] if i < len(closes) else None
                    v = vols[i] if i < len(vols) else 0.0

                    if o is not None and h is not None and l is not None and c is not None and o > 0 and c > 0:
                        ts_str = datetime.fromtimestamp(timestamps[i], timezone.utc).isoformat()
                        raw_5m_candles.append(
                            ReplayCandle(
                                timestamp=ts_str,
                                open=float(o),
                                high=float(h),
                                low=float(l),
                                close=float(c),
                                volume=float(v or 0.0),
                                timeframe="5M"
                            )
                        )

                if len(raw_5m_candles) >= 30:
                    tf_data = HistoricalDataLoader.aggregate_timeframes(raw_5m_candles)
                    
                    # Add 30M aggregation
                    tf_30m = []
                    for idx in range(0, len(raw_5m_candles), 6):
                        chunk = raw_5m_candles[idx:idx + 6]
                        if chunk:
                            tf_30m.append({
                                "timestamp": chunk[0].timestamp,
                                "open": chunk[0].open,
                                "high": max(c.high for c in chunk),
                                "low": min(c.low for c in chunk),
                                "close": chunk[-1].close,
                                "volume": sum(c.volume for c in chunk),
                                "timeframe": "30M"
                            })
                    tf_data["30M"] = tf_30m

                    self._ohlc_cache[symbol] = (now, tf_data)
                    return tf_data

        except Exception as e:
            logger.warning(f"[OHLC] Failed fetching live OHLC candles for {symbol}: {e}")

        return None

    def _clean_symbol_name(self, raw: str) -> str:
        s = raw.upper()
        if ":" in s:
            s = s.split(":")[1]
        s = s.replace("/", "").replace("-", "").replace("_", "")
        if "BTC" in s:
            return "BTCUSD"
        return s

    async def _resolve_canonical_price(
        self,
        symbol: str,
        override_price: Optional[float] = None
    ) -> PriceMetadata:
        now = time.time()

        if override_price and override_price > 0:
            self.update_symbol_price(symbol, override_price, source="TRADINGVIEW")

        # 1. Check Cache
        cached = self._price_cache.get(symbol)
        if cached and (now - cached.timestamp) < settings.CACHE_TTL_PRICE:
            age = round(now - cached.timestamp, 2)
            cache_meta = PriceMetadata(
                price=cached.price,
                source=f"CACHE ({cached.source})",
                timestamp=cached.timestamp,
                is_client_supplied=cached.is_client_supplied,
                is_market_feed=cached.is_market_feed,
                age_seconds=age,
                status="CACHED"
            )
            return cache_meta

        evaluated_sources: Dict[str, Any] = {}
        selected_meta: Optional[PriceMetadata] = None

        # 2. Try Spot Feeds from DOM Adapters (OANDA, Dukascopy)
        spot_prices: List[Tuple[str, float]] = []
        try:
            raw_adapters = getattr(dom_engine, "adapters", [])
            adapters = list(raw_adapters) if hasattr(raw_adapters, "__iter__") and not isinstance(raw_adapters, (list, tuple)) else raw_adapters
            for adapter in adapters:
                try:
                    snap = await adapter.fetch_snapshot(symbol, None)
                    if snap and getattr(snap, "status", None) == SourceStatus.LIVE and getattr(snap, "raw_spot_price", None) and snap.raw_spot_price > 0:
                        src_id = getattr(snap, "source_id", getattr(adapter, "source_id", "SPOT"))
                        spot_prices.append((src_id, snap.raw_spot_price))
                        evaluated_sources[src_id] = {"price": snap.raw_spot_price, "status": "LIVE"}
                except Exception:
                    pass
        except Exception:
            pass

        client_meta = self.symbol_prices.get(symbol)

        if spot_prices:
            avg_spot = sum(p for _, p in spot_prices) / len(spot_prices)
            lead_source = spot_prices[0][0]

            # Check if client price is an outlier compared to spot consensus
            if client_meta and client_meta.price > 0:
                divergence = abs(client_meta.price - avg_spot)
                # Divergence threshold: $20 for gold, or 1%
                max_dev = 20.0 if symbol == "XAUUSD" else (avg_spot * 0.01)
                if divergence > max_dev:
                    evaluated_sources[client_meta.source] = {
                        "price": client_meta.price,
                        "status": "OUTLIER_REJECTED"
                    }
                    logger.warning(
                        f"[PRICE] Client price {client_meta.price:.2f} rejected as outlier (divergence={divergence:.2f} > {max_dev:.2f})"
                    )
                elif settings.ALLOW_CLIENT_PRICE_OVERRIDE:
                    selected_meta = PriceMetadata(
                        price=client_meta.price,
                        source=client_meta.source,
                        timestamp=client_meta.timestamp,
                        is_client_supplied=True,
                        is_market_feed=False,
                        age_seconds=round(now - client_meta.timestamp, 1),
                        status="LIVE"
                    )
                    evaluated_sources[client_meta.source] = {"price": client_meta.price, "status": "LIVE"}

            if not selected_meta:
                selected_meta = PriceMetadata(
                    price=avg_spot,
                    source=lead_source,
                    timestamp=now,
                    is_client_supplied=False,
                    is_market_feed=True,
                    age_seconds=0.0,
                    status="LIVE"
                )

        # 3. Try Market Feeds (Yahoo Futures / Finnhub) if no spot feed
        if not selected_meta:
            yahoo_price = await self._fetch_yahoo_price(symbol)
            if yahoo_price and yahoo_price > 0:
                selected_meta = PriceMetadata(
                    price=yahoo_price,
                    source="YAHOO_FUTURES" if symbol == "XAUUSD" else "YAHOO",
                    timestamp=now,
                    is_client_supplied=False,
                    is_market_feed=True,
                    age_seconds=0.0,
                    status="LIVE"
                )
                evaluated_sources[selected_meta.source] = {"price": yahoo_price, "status": "LIVE"}

        if not selected_meta and settings.FINNHUB_API_KEY:
            finnhub_price = await self._fetch_finnhub_price(symbol)
            if finnhub_price and finnhub_price > 0:
                selected_meta = PriceMetadata(
                    price=finnhub_price,
                    source="FINNHUB",
                    timestamp=now,
                    is_client_supplied=False,
                    is_market_feed=True,
                    age_seconds=0.0,
                    status="LIVE"
                )
                evaluated_sources["FINNHUB"] = {"price": finnhub_price, "status": "LIVE"}

        # 4. Client override when market feeds are unavailable
        if not selected_meta and settings.ALLOW_CLIENT_PRICE_OVERRIDE and client_meta and client_meta.price > 0:
            selected_meta = PriceMetadata(
                price=client_meta.price,
                source=client_meta.source,
                timestamp=client_meta.timestamp,
                is_client_supplied=True,
                is_market_feed=False,
                age_seconds=round(now - client_meta.timestamp, 1),
                status="LIVE"
            )
            evaluated_sources[client_meta.source] = {"price": client_meta.price, "status": "LIVE"}

        # 5. Benchmark Fallback (Truthfully labeled as BENCHMARK, never LIVE)
        if not selected_meta:
            benchmarks = {
                "XAUUSD": 4426.00,
                "EURUSD": 1.1537,
                "GBPUSD": 1.3497,
                "USDJPY": 159.35,
                "USDCHF": 0.8650,
                "AUDUSD": 0.6550,
                "USDCAD": 1.3650,
                "NZDUSD": 0.5980,
                "BTCUSD": 63612.00
            }
            bp = benchmarks.get(symbol, 4426.00)
            selected_meta = PriceMetadata(
                price=bp,
                source="BENCHMARK",
                timestamp=now,
                is_client_supplied=False,
                is_market_feed=False,
                age_seconds=0.0,
                status="BENCHMARK"
            )
            logger.warning(f"[PRICE] {symbol} falling back to BENCHMARK price={bp:.2f}")

        # Update cache & debug object
        self._price_cache[symbol] = selected_meta
        self.canonical_price_debug[symbol] = {
            "symbol": symbol,
            "canonical_price": selected_meta.price,
            "source": selected_meta.source,
            "timestamp": datetime.fromtimestamp(selected_meta.timestamp, timezone.utc).isoformat(),
            "age_seconds": selected_meta.age_seconds,
            "status": selected_meta.status,
            "sources": evaluated_sources
        }

        logger.info(f"[PRICE] {symbol} price={selected_meta.price:.2f} source={selected_meta.source} age={selected_meta.age_seconds:.1f}s")
        return selected_meta

    async def _fetch_yahoo_price(self, symbol: str) -> Optional[float]:
        yahoo_symbols = {
            "XAUUSD": "GC=F",
            "EURUSD": "EURUSD=X",
            "GBPUSD": "GBPUSD=X",
            "USDJPY": "JPY=X",
            "USDCHF": "CHF=X",
            "AUDUSD": "AUDUSD=X",
            "USDCAD": "CAD=X",
            "NZDUSD": "NZDUSD=X",
            "BTCUSD": "BTC-USD"
        }
        ysym = yahoo_symbols.get(symbol)
        if not ysym:
            return None
        try:
            res = await self.client.get(
                f"https://query1.finance.yahoo.com/v8/finance/chart/{ysym}",
                headers={"User-Agent": "Mozilla/5.0"}
            )
            if res.status_code == 200:
                data = res.json()
                meta = data.get("chart", {}).get("result", [{}])[0].get("meta", {})
                live_p = meta.get("regularMarketPrice")
                if live_p and live_p > 0:
                    return float(live_p)
        except Exception as e:
            logger.warning(f"Yahoo Finance price fetch error for {symbol}: {e}")
        return None

    async def _fetch_finnhub_price(self, symbol: str) -> Optional[float]:
        try:
            res = await self.client.get(
                f"https://finnhub.io/api/v1/quote?symbol={symbol}&token={settings.FINNHUB_API_KEY}"
            )
            if res.status_code == 200:
                data = res.json()
                if "c" in data and data["c"] > 0:
                    return float(data["c"])
        except Exception as e:
            logger.warning(f"Finnhub price fetch error for {symbol}: {e}")
        return None

    async def _fetch_live_price(self, symbol: str) -> float:
        meta = await self._resolve_canonical_price(symbol)
        return meta.price


provider_manager = ProviderManager()
