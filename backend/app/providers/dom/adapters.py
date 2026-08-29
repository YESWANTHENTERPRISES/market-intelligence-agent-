import time
import logging
import threading
from typing import Optional, Dict, List, Any
from app.core.config import settings
from app.providers.dom.models import SourceSnapshot, SourceStatus, PriceLevel

logger = logging.getLogger("dom_adapters")

# Defensive import for MetaTrader5 (Windows only / optional dependency)
try:
    import MetaTrader5 as mt5
    MT5_AVAILABLE = True
except (ImportError, Exception):
    mt5 = None
    MT5_AVAILABLE = False


class BaseDOMAdapter:
    source_id: str = "base"
    source_name: str = "Base Source"
    default_weight: float = 0.50

    async def fetch_snapshot(self, symbol: str, current_price: Optional[float] = None) -> SourceSnapshot:
        raise NotImplementedError


def _get_price_step(p: float) -> float:
    if p < 5.0:
        return max(0.0020, p * 0.0020)
    elif p < 250.0:
        return max(0.40, p * 0.0030)
    elif p > 10000.0:
        return max(800.0, p * 0.010)
    else:
        return max(4.0, p * 0.002)


class MT5DOMAdapter(BaseDOMAdapter):
    """
    MetaTrader 5 Depth of Market (DOM) Adapter.
    Communicates with local/remote MetaTrader 5 terminal via the MetaTrader5 Python IPC package.
    Extracts L2 market book depth (bids and asks) and top-of-book spot prices.
    """
    source_id = "MT5"
    source_name = "MetaTrader 5"
    default_weight = 0.50

    def __init__(self, simulate: bool = False):
        self.simulate = simulate
        self._initialized = False

    def _ensure_initialized(self) -> bool:
        if not MT5_AVAILABLE:
            return False
        if not settings.MT5_ENABLED:
            return False
        if self._initialized:
            # Verify terminal is still active
            try:
                if mt5.terminal_info() is not None:
                    return True
            except Exception:
                pass

        try:
            init_kwargs: Dict[str, Any] = {
                "timeout": settings.MT5_TIMEOUT,
                "portable": settings.MT5_PORTABLE,
            }
            if settings.MT5_PATH:
                init_kwargs["path"] = settings.MT5_PATH
            if settings.MT5_LOGIN:
                init_kwargs["login"] = settings.MT5_LOGIN
            if settings.MT5_PASSWORD:
                init_kwargs["password"] = settings.MT5_PASSWORD
            if settings.MT5_SERVER:
                init_kwargs["server"] = settings.MT5_SERVER

            ok = mt5.initialize(**init_kwargs)
            if ok:
                self._initialized = True
                logger.info("[MT5] Successfully initialized MetaTrader 5 terminal connection")
                return True
            else:
                err = mt5.last_error()
                logger.warning(f"[MT5] Initialization failed: {err}")
                self._initialized = False
                return False
        except Exception as e:
            logger.warning(f"[MT5] Exception during initialize: {e}")
            self._initialized = False
            return False

    async def fetch_snapshot(self, symbol: str, current_price: Optional[float] = None) -> SourceSnapshot:
        now = time.time()

        # 1. Explicit Simulation / Testing Mode
        if self.simulate:
            p = float(current_price) if current_price and current_price > 0 else 4431.00
            step = _get_price_step(p)
            return SourceSnapshot(
                source_id=self.source_id,
                source_name=self.source_name,
                status=SourceStatus.SIMULATED,
                observed_timestamp=now,
                freshness_seconds=0.1,
                freshness_label="SIMULATED",
                raw_contract_unit="lots",
                included_in_aggregation=False,
                bids=[
                    PriceLevel(price=round(p - 0.5 * step, 2), volume=120.0),
                    PriceLevel(price=round(p - 1.0 * step, 2), volume=250.0),
                ],
                asks=[
                    PriceLevel(price=round(p + 0.5 * step, 2), volume=140.0),
                    PriceLevel(price=round(p + 1.0 * step, 2), volume=310.0),
                ],
                raw_spot_price=round(p, 2)
            )

        # 2. Check Prerequisites (Config & Package)
        if not settings.MT5_ENABLED or not MT5_AVAILABLE:
            return SourceSnapshot(
                source_id=self.source_id,
                source_name=self.source_name,
                status=SourceStatus.UNAVAILABLE,
                observed_timestamp=now,
                freshness_seconds=0.0,
                freshness_label="UNAVAILABLE",
                raw_contract_unit="lots",
                included_in_aggregation=False,
                bids=[],
                asks=[],
                raw_spot_price=None
            )

        # 3. Live Query Execution
        try:
            if not self._ensure_initialized():
                return SourceSnapshot(
                    source_id=self.source_id,
                    source_name=self.source_name,
                    status=SourceStatus.UNAVAILABLE,
                    observed_timestamp=now,
                    freshness_seconds=0.0,
                    freshness_label="UNAVAILABLE",
                    raw_contract_unit="lots",
                    included_in_aggregation=False,
                    bids=[],
                    asks=[],
                    raw_spot_price=None
                )

            # Resolve mapped symbol name
            mt5_sym = settings.MT5_SYMBOL_MAP.get(symbol, symbol)

            # Ensure symbol is selected in Market Watch
            if not mt5.symbol_select(mt5_sym, True):
                logger.warning(f"[MT5] Failed to select symbol '{mt5_sym}' in MarketWatch")
                return SourceSnapshot(
                    source_id=self.source_id,
                    source_name=self.source_name,
                    status=SourceStatus.UNAVAILABLE,
                    observed_timestamp=now,
                    freshness_seconds=0.0,
                    freshness_label="UNAVAILABLE",
                    raw_contract_unit="lots",
                    included_in_aggregation=False,
                    bids=[],
                    asks=[],
                    raw_spot_price=None
                )

            # Subscribe to Depth of Market
            mt5.market_book_add(mt5_sym)

            # Fetch Book and Tick
            book_items = mt5.market_book_get(mt5_sym)
            tick = mt5.symbol_info_tick(mt5_sym)

            spot_price = float(tick.bid) if (tick and getattr(tick, "bid", 0) > 0) else None

            bids: List[PriceLevel] = []
            asks: List[PriceLevel] = []

            if book_items:
                # MT5 book types: BOOK_TYPE_BUY (1), BOOK_TYPE_SELL (2)
                type_buy = getattr(mt5, "BOOK_TYPE_BUY", 1)
                type_buy_mkt = getattr(mt5, "BOOK_TYPE_BUY_MARKET", 3)
                type_sell = getattr(mt5, "BOOK_TYPE_SELL", 2)
                type_sell_mkt = getattr(mt5, "BOOK_TYPE_SELL_MARKET", 4)

                for item in book_items:
                    p_val = float(getattr(item, "price", 0.0))
                    v_val = float(getattr(item, "volume", 0.0))
                    t_val = getattr(item, "type", 0)

                    if p_val <= 0 or v_val <= 0:
                        continue

                    if t_val in [type_buy, type_buy_mkt]:
                        bids.append(PriceLevel(price=p_val, volume=v_val))
                    elif t_val in [type_sell, type_sell_mkt]:
                        asks.append(PriceLevel(price=p_val, volume=v_val))

            # If both book and tick are absent, return UNAVAILABLE
            if not bids and not asks and spot_price is None:
                return SourceSnapshot(
                    source_id=self.source_id,
                    source_name=self.source_name,
                    status=SourceStatus.UNAVAILABLE,
                    observed_timestamp=now,
                    freshness_seconds=0.0,
                    freshness_label="UNAVAILABLE",
                    raw_contract_unit="lots",
                    included_in_aggregation=False,
                    bids=[],
                    asks=[],
                    raw_spot_price=None
                )

            # Calculate freshness from tick timestamp if available
            tick_ts = float(getattr(tick, "time", now)) if tick else now
            age = max(0.0, round(now - tick_ts, 1))
            status = SourceStatus.LIVE if age < 15.0 else SourceStatus.STALE

            return SourceSnapshot(
                source_id=self.source_id,
                source_name=self.source_name,
                status=status,
                observed_timestamp=now,
                freshness_seconds=age,
                freshness_label="LIVE" if status == SourceStatus.LIVE else "STALE",
                raw_contract_unit="lots",
                included_in_aggregation=(status == SourceStatus.LIVE),
                bids=bids,
                asks=asks,
                raw_spot_price=spot_price
            )

        except Exception as e:
            logger.warning(f"[MT5] Error fetching snapshot for {symbol}: {e}")
            return SourceSnapshot(
                source_id=self.source_id,
                source_name=self.source_name,
                status=SourceStatus.UNAVAILABLE,
                observed_timestamp=now,
                freshness_seconds=0.0,
                freshness_label="UNAVAILABLE",
                raw_contract_unit="lots",
                included_in_aggregation=False,
                bids=[],
                asks=[],
                raw_spot_price=None
            )


class CTraderDOMAdapter(BaseDOMAdapter):
    """
    Spotware cTrader Open API Depth of Market (DOM) Adapter.
    Connects to cTrader Open API Protobuf/WebSocket service to stream L2 market depth.
    Runs background client connection with thread-safe data synchronization.
    """
    source_id = "CTRADER"
    source_name = "cTrader Open API"
    default_weight = 0.50

    def __init__(self, simulate: bool = False):
        self.simulate = simulate
        self._lock = threading.Lock()
        self._depth_cache: Dict[str, Dict[str, Any]] = {}
        self._connected = False
        self._worker_thread: Optional[threading.Thread] = None

    def update_cached_depth(
        self,
        symbol: str,
        spot_price: Optional[float],
        bids: List[PriceLevel],
        asks: List[PriceLevel],
        observed_ts: Optional[float] = None
    ) -> None:
        """Thread-safe update method for background cTrader stream worker."""
        with self._lock:
            self._depth_cache[symbol] = {
                "timestamp": observed_ts or time.time(),
                "spot_price": spot_price,
                "bids": bids,
                "asks": asks,
            }
            self._connected = True

    def set_connected(self, state: bool) -> None:
        with self._lock:
            self._connected = state

    async def fetch_snapshot(self, symbol: str, current_price: Optional[float] = None) -> SourceSnapshot:
        now = time.time()

        # 1. Explicit Simulation / Testing Mode
        if self.simulate:
            p = float(current_price) if current_price and current_price > 0 else 4431.00
            step = _get_price_step(p)
            return SourceSnapshot(
                source_id=self.source_id,
                source_name=self.source_name,
                status=SourceStatus.SIMULATED,
                observed_timestamp=now,
                freshness_seconds=0.2,
                freshness_label="SIMULATED",
                raw_contract_unit="lots",
                included_in_aggregation=False,
                bids=[
                    PriceLevel(price=round(p - 0.4 * step, 2), volume=180.0),
                    PriceLevel(price=round(p - 0.9 * step, 2), volume=320.0),
                ],
                asks=[
                    PriceLevel(price=round(p + 0.4 * step, 2), volume=160.0),
                    PriceLevel(price=round(p + 0.9 * step, 2), volume=290.0),
                ],
                raw_spot_price=round(p, 2)
            )

        # 2. Check Prerequisites (Config & Credentials)
        if (
            not settings.CTRADER_ENABLED
            or not settings.CTRADER_CLIENT_ID
            or not settings.CTRADER_ACCESS_TOKEN
            or not settings.CTRADER_ACCOUNT_ID
        ):
            return SourceSnapshot(
                source_id=self.source_id,
                source_name=self.source_name,
                status=SourceStatus.UNAVAILABLE,
                observed_timestamp=now,
                freshness_seconds=0.0,
                freshness_label="UNAVAILABLE",
                raw_contract_unit="lots",
                included_in_aggregation=False,
                bids=[],
                asks=[],
                raw_spot_price=None
            )

        # 3. Read from Thread-Safe Depth Cache
        with self._lock:
            cached = self._depth_cache.get(symbol)
            is_conn = self._connected

        if not is_conn or not cached:
            return SourceSnapshot(
                source_id=self.source_id,
                source_name=self.source_name,
                status=SourceStatus.UNAVAILABLE,
                observed_timestamp=now,
                freshness_seconds=0.0,
                freshness_label="UNAVAILABLE",
                raw_contract_unit="lots",
                included_in_aggregation=False,
                bids=[],
                asks=[],
                raw_spot_price=None
            )

        ts = cached.get("timestamp", 0.0)
        age = max(0.0, round(now - ts, 1))

        if age > 10.0:
            return SourceSnapshot(
                source_id=self.source_id,
                source_name=self.source_name,
                status=SourceStatus.STALE,
                observed_timestamp=ts,
                freshness_seconds=age,
                freshness_label=f"STALE ({age:.0f}s)",
                raw_contract_unit="lots",
                included_in_aggregation=False,
                bids=cached.get("bids", []),
                asks=cached.get("asks", []),
                raw_spot_price=cached.get("spot_price")
            )

        return SourceSnapshot(
            source_id=self.source_id,
            source_name=self.source_name,
            status=SourceStatus.LIVE,
            observed_timestamp=ts,
            freshness_seconds=age,
            freshness_label="LIVE",
            raw_contract_unit="lots",
            included_in_aggregation=True,
            bids=cached.get("bids", []),
            asks=cached.get("asks", []),
            raw_spot_price=cached.get("spot_price")
        )


# Aliases for convenience
MT5Adapter = MT5DOMAdapter
MetaTrader5Adapter = MT5DOMAdapter
CTraderAdapter = CTraderDOMAdapter
