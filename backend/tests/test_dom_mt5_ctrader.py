import time
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from app.core.config import settings
from app.providers.dom.models import SourceSnapshot, SourceStatus, PriceLevel, DOMIntelligenceData
from app.providers.dom.adapters import MT5DOMAdapter, CTraderDOMAdapter
from app.providers.dom.engine import DOMEngine


# 1. Environment without credentials / Both Disabled
@pytest.mark.asyncio
async def test_both_adapters_disabled_no_credentials():
    with patch.object(settings, "MT5_ENABLED", False):
        with patch.object(settings, "CTRADER_ENABLED", False):
            engine = DOMEngine()
            dom_intel = await engine.build_dom_intelligence("XAUUSD", 4431.00)

            assert isinstance(dom_intel, DOMIntelligenceData)
            assert dom_intel.coverage == "NO-SOURCE (0/2)"
            assert len(dom_intel.sources) == 2

            for s in dom_intel.sources:
                assert s.included_in_aggregation is False
                assert s.status == "UNAVAILABLE"

            assert dom_intel.liquidity_status == "DATA NOT VERIFIED"
            assert dom_intel.retail_positioning == "UNAVAILABLE"
            assert dom_intel.futures_sell_wall == "UNAVAILABLE"
            assert dom_intel.data_quality == "UNAVAILABLE"


# 2. MT5 Adapter Failure & Graceful Degradation
@pytest.mark.asyncio
async def test_mt5_adapter_import_error_or_missing_terminal():
    adapter = MT5DOMAdapter()
    
    # 1. MT5 not enabled
    with patch.object(settings, "MT5_ENABLED", False):
        snap = await adapter.fetch_snapshot("XAUUSD", 4431.00)
        assert snap.status == SourceStatus.UNAVAILABLE
        assert snap.included_in_aggregation is False

    # 2. MT5 enabled but terminal initialize fails
    with patch.object(settings, "MT5_ENABLED", True):
        with patch("app.providers.dom.adapters.MT5_AVAILABLE", True):
            with patch("app.providers.dom.adapters.mt5") as mock_mt5:
                mock_mt5.terminal_info.return_value = None
                mock_mt5.initialize.return_value = False
                mock_mt5.last_error.return_value = (-1, "Terminal not running")

                snap = await adapter.fetch_snapshot("XAUUSD", 4431.00)
                assert snap.status == SourceStatus.UNAVAILABLE
                assert snap.included_in_aggregation is False


# 3. MT5 Adapter Live Book Retrieval
@pytest.mark.asyncio
async def test_mt5_adapter_live_book_retrieval():
    adapter = MT5DOMAdapter()

    mock_book_item_buy = MagicMock()
    mock_book_item_buy.price = 4430.50
    mock_book_item_buy.volume = 15.0
    mock_book_item_buy.type = 1  # BOOK_TYPE_BUY

    mock_book_item_sell = MagicMock()
    mock_book_item_sell.price = 4431.50
    mock_book_item_sell.volume = 20.0
    mock_book_item_sell.type = 2  # BOOK_TYPE_SELL

    mock_tick = MagicMock()
    mock_tick.bid = 4431.00
    mock_tick.ask = 4431.20
    mock_tick.time = time.time()

    with patch.object(settings, "MT5_ENABLED", True):
        with patch("app.providers.dom.adapters.MT5_AVAILABLE", True):
            with patch("app.providers.dom.adapters.mt5") as mock_mt5:
                mock_mt5.terminal_info.return_value = MagicMock()
                mock_mt5.initialize.return_value = True
                mock_mt5.symbol_select.return_value = True
                mock_mt5.market_book_add.return_value = True
                mock_mt5.market_book_get.return_value = [mock_book_item_buy, mock_book_item_sell]
                mock_mt5.symbol_info_tick.return_value = mock_tick
                mock_mt5.BOOK_TYPE_BUY = 1
                mock_mt5.BOOK_TYPE_SELL = 2
                mock_mt5.BOOK_TYPE_BUY_MARKET = 3
                mock_mt5.BOOK_TYPE_SELL_MARKET = 4

                snap = await adapter.fetch_snapshot("XAUUSD", 4431.00)
                assert snap.status == SourceStatus.LIVE
                assert snap.included_in_aggregation is True
                assert snap.raw_spot_price == pytest.approx(4431.00)
                assert len(snap.bids) == 1
                assert snap.bids[0].price == pytest.approx(4430.50)
                assert len(snap.asks) == 1
                assert snap.asks[0].price == pytest.approx(4431.50)


# 4. cTrader Adapter Credential Checks & Thread-Safe Cache
@pytest.mark.asyncio
async def test_ctrader_adapter_missing_credentials_and_live_cache():
    adapter = CTraderDOMAdapter()

    # 1. Missing credentials
    with patch.object(settings, "CTRADER_ENABLED", False):
        snap = await adapter.fetch_snapshot("XAUUSD", 4431.00)
        assert snap.status == SourceStatus.UNAVAILABLE
        assert snap.included_in_aggregation is False

    # 2. Enabled with fresh cache
    with patch.object(settings, "CTRADER_ENABLED", True):
        with patch.object(settings, "CTRADER_CLIENT_ID", "client_123"):
            with patch.object(settings, "CTRADER_ACCESS_TOKEN", "token_abc"):
                with patch.object(settings, "CTRADER_ACCOUNT_ID", 123456):
                    # Unconnected / empty cache -> UNAVAILABLE
                    snap_empty = await adapter.fetch_snapshot("XAUUSD", 4431.00)
                    assert snap_empty.status == SourceStatus.UNAVAILABLE

                    # Update depth cache
                    adapter.update_cached_depth(
                        symbol="XAUUSD",
                        spot_price=4431.00,
                        bids=[PriceLevel(price=4430.00, volume=50.0)],
                        asks=[PriceLevel(price=4432.00, volume=60.0)],
                        observed_ts=time.time()
                    )

                    snap_live = await adapter.fetch_snapshot("XAUUSD", 4431.00)
                    assert snap_live.status == SourceStatus.LIVE
                    assert snap_live.included_in_aggregation is True
                    assert len(snap_live.bids) == 1
                    assert len(snap_live.asks) == 1

                    # Stale cache (>10s) -> STALE
                    adapter.update_cached_depth(
                        symbol="XAUUSD",
                        spot_price=4431.00,
                        bids=[PriceLevel(price=4430.00, volume=50.0)],
                        asks=[PriceLevel(price=4432.00, volume=60.0)],
                        observed_ts=time.time() - 15.0
                    )
                    snap_stale = await adapter.fetch_snapshot("XAUUSD", 4431.00)
                    assert snap_stale.status == SourceStatus.STALE
                    assert snap_stale.included_in_aggregation is False


# 5. Dynamic Coverage Strings with Varied Source Availability
@pytest.mark.asyncio
async def test_dynamic_source_coverage_combinations():
    engine = DOMEngine()

    # Case A: Only MT5 active
    engine.adapters[0].fetch_snapshot = AsyncMock(return_value=SourceSnapshot(
        source_id="MT5", source_name="MetaTrader 5", status=SourceStatus.LIVE,
        observed_timestamp=time.time(), raw_spot_price=4431.00,
        bids=[PriceLevel(price=4430.0, volume=100.0)],
        asks=[PriceLevel(price=4432.0, volume=100.0)],
        included_in_aggregation=True
    ))
    engine.adapters[1].fetch_snapshot = AsyncMock(return_value=SourceSnapshot(
        source_id="CTRADER", source_name="cTrader Open API", status=SourceStatus.UNAVAILABLE,
        observed_timestamp=time.time(), included_in_aggregation=False
    ))
    dom_intel_1 = await engine.build_dom_intelligence("XAUUSD", 4431.00)
    assert dom_intel_1.coverage == "SINGLE-SOURCE (1/2)"
    assert dom_intel_1.liquidity_status == "VERIFIED"
    assert dom_intel_1.data_quality == "MODERATE"

    # Case B: Both MT5 and cTrader active
    engine.adapters[1].fetch_snapshot = AsyncMock(return_value=SourceSnapshot(
        source_id="CTRADER", source_name="cTrader Open API", status=SourceStatus.LIVE,
        observed_timestamp=time.time(), raw_spot_price=4431.00,
        bids=[PriceLevel(price=4429.0, volume=80.0)],
        asks=[PriceLevel(price=4433.0, volume=90.0)],
        included_in_aggregation=True
    ))
    dom_intel_2 = await engine.build_dom_intelligence("XAUUSD", 4431.00)
    assert dom_intel_2.coverage == "MULTI-SOURCE (2/2)"
    assert dom_intel_2.data_quality == "HIGH"
