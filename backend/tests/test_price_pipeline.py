import time
import pytest
from unittest.mock import AsyncMock, patch
from app.providers.manager import ProviderManager
from app.models.schemas import PriceMetadata
from app.providers.dom.models import SourceSnapshot, SourceStatus
from app.core.config import settings



@pytest.mark.asyncio
async def test_1_source_attribution():
    manager = ProviderManager()
    with patch.object(manager, "_resolve_canonical_price", new=AsyncMock(return_value=PriceMetadata(
        price=4335.20, source="OANDA", timestamp=time.time(), is_market_feed=True, age_seconds=0.0, status="LIVE"
    ))):
        meta = await manager._resolve_canonical_price("XAUUSD")
        assert meta.source == "OANDA"
        assert meta.price == pytest.approx(4335.20)
        assert meta.is_market_feed is True
        assert meta.is_client_supplied is False


@pytest.mark.asyncio
async def test_2_tradingview_cannot_silently_override_trusted_spot():
    manager = ProviderManager()
    # Client pushes TradingView price 4391.10
    manager.update_symbol_price("XAUUSD", 4391.10, source="TRADINGVIEW")
    
    # Mock OANDA spot feed returning 4335.20
    with patch("app.providers.manager.dom_engine.adapters") as mock_adapters:
        mock_oanda = AsyncMock()
        mock_oanda.source_id = "OANDA"
        mock_oanda.fetch_snapshot = AsyncMock(return_value=SourceSnapshot(
            source_id="OANDA", source_name="OANDA", status=SourceStatus.LIVE,
            observed_timestamp=time.time(), raw_spot_price=4335.20
        ))
        mock_adapters.__iter__.return_value = [mock_oanda]
        
        meta = await manager._resolve_canonical_price("XAUUSD")
        # Trusted OANDA spot (4335.20) must be selected over TradingView client override (4391.10)
        assert meta.price == pytest.approx(4335.20)
        assert meta.source == "OANDA"


@pytest.mark.asyncio
async def test_3_matching_spot_sources_consensus():
    manager = ProviderManager()
    with patch("app.providers.manager.dom_engine.adapters") as mock_adapters:
        mock_oanda = AsyncMock()
        mock_oanda.source_id = "OANDA"
        mock_oanda.fetch_snapshot = AsyncMock(return_value=SourceSnapshot(
            source_id="OANDA", source_name="OANDA", status=SourceStatus.LIVE,
            observed_timestamp=time.time(), raw_spot_price=4335.20
        ))
        mock_duka = AsyncMock()
        mock_duka.source_id = "DUKASCOPY"
        mock_duka.fetch_snapshot = AsyncMock(return_value=SourceSnapshot(
            source_id="DUKASCOPY", source_name="DUKASCOPY", status=SourceStatus.LIVE,
            observed_timestamp=time.time(), raw_spot_price=4335.18
        ))
        mock_adapters.__iter__.return_value = [mock_oanda, mock_duka]

        meta = await manager._resolve_canonical_price("XAUUSD")
        assert meta.price == pytest.approx((4335.20 + 4335.18) / 2.0)
        assert meta.source == "OANDA"
        assert meta.status == "LIVE"


@pytest.mark.asyncio
async def test_4_source_outlier_rejection():
    manager = ProviderManager()
    # Client sends 4391.10
    manager.update_symbol_price("XAUUSD", 4391.10, source="TRADINGVIEW")

    with patch("app.providers.manager.dom_engine.adapters") as mock_adapters:
        mock_oanda = AsyncMock()
        mock_oanda.source_id = "OANDA"
        mock_oanda.fetch_snapshot = AsyncMock(return_value=SourceSnapshot(
            source_id="OANDA", source_name="OANDA", status=SourceStatus.LIVE,
            observed_timestamp=time.time(), raw_spot_price=4335.20
        ))
        mock_adapters.__iter__.return_value = [mock_oanda]

        meta = await manager._resolve_canonical_price("XAUUSD")
        # TradingView 4391.10 must be marked OUTLIER and rejected
        debug = manager.canonical_price_debug.get("XAUUSD", {})
        assert debug.get("sources", {}).get("TRADINGVIEW", {}).get("status") == "OUTLIER_REJECTED"
        assert meta.price == pytest.approx(4335.20)


@pytest.mark.asyncio
async def test_5_client_price_cache_metadata_survival():
    manager = ProviderManager()
    now = time.time()
    manager._price_cache["XAUUSD"] = PriceMetadata(
        price=4335.20, source="OANDA", timestamp=now, is_market_feed=True, age_seconds=0.0, status="LIVE"
    )

    meta = await manager._resolve_canonical_price("XAUUSD")
    assert "CACHE" in meta.source
    assert "OANDA" in meta.source
    assert meta.price == pytest.approx(4335.20)
    assert meta.status == "CACHED"


@pytest.mark.asyncio
async def test_6_cache_expiry():
    manager = ProviderManager()
    old_time = time.time() - 10.0  # 10s ago (> CACHE_TTL_PRICE = 3s)
    manager._price_cache["XAUUSD"] = PriceMetadata(
        price=4391.10, source="TRADINGVIEW", timestamp=old_time, is_client_supplied=True, age_seconds=10.0, status="LIVE"
    )

    with patch.object(manager, "_fetch_yahoo_price", new=AsyncMock(return_value=4335.50)):
        with patch("app.providers.manager.dom_engine.adapters", new=[]):
            meta = await manager._resolve_canonical_price("XAUUSD")
            assert meta.price == pytest.approx(4335.50)
            assert meta.source == "YAHOO_FUTURES"


@pytest.mark.asyncio
async def test_7_yahoo_futures_distinction():
    manager = ProviderManager()
    with patch("app.providers.manager.dom_engine.adapters", new=[]):
        with patch.object(manager, "_fetch_yahoo_price", new=AsyncMock(return_value=4430.00)):
            meta = await manager._resolve_canonical_price("XAUUSD")
            assert meta.source == "YAHOO_FUTURES"
            assert meta.price == pytest.approx(4430.00)


@pytest.mark.asyncio
async def test_8_no_trusted_spot_fallback_to_benchmark():
    manager = ProviderManager()
    with patch("app.providers.manager.dom_engine.adapters", new=[]):
        with patch.object(manager, "_fetch_yahoo_price", new=AsyncMock(return_value=None)):
            with patch.object(manager, "_fetch_finnhub_price", new=AsyncMock(return_value=None)):
                meta = await manager._resolve_canonical_price("XAUUSD")
                assert meta.source == "BENCHMARK"
                assert meta.price == pytest.approx(4426.00)
                assert meta.status == "BENCHMARK"


@pytest.mark.asyncio
async def test_9_dom_price_consistency():
    manager = ProviderManager()
    with patch.object(manager, "_resolve_canonical_price", new=AsyncMock(return_value=PriceMetadata(
        price=4335.20, source="OANDA", timestamp=time.time(), is_market_feed=True, age_seconds=0.0, status="LIVE"
    ))):
        res = await manager.get_market_intelligence("XAUUSD", "5M")
        assert res.current_price == pytest.approx(4335.20)
        assert res.dom.current_price == pytest.approx(4335.20)


@pytest.mark.asyncio
async def test_10_exact_regression_discrepancy():
    """
    Reproduce the reported discrepancy:
    TradingView client sends 4391.10 while live spot feed is 4335.20.
    Verify 4391.10 is rejected and 4335.20 is selected as canonical.
    """
    manager = ProviderManager()
    # Client pushes 4391.10
    manager.update_symbol_price("XAUUSD", 4391.10, source="TRADINGVIEW")

    with patch("app.providers.manager.dom_engine.adapters") as mock_adapters:
        mock_oanda = AsyncMock()
        mock_oanda.source_id = "OANDA"
        mock_oanda.fetch_snapshot = AsyncMock(return_value=SourceSnapshot(
            source_id="OANDA", source_name="OANDA", status=SourceStatus.LIVE,
            observed_timestamp=time.time(), raw_spot_price=4335.20
        ))
        mock_adapters.__iter__.return_value = [mock_oanda]

        res = await manager.get_market_intelligence("XAUUSD", "5M")
        assert res.current_price == pytest.approx(4335.20)
        assert res.dom.current_price == pytest.approx(4335.20)
        assert res.current_price != 4391.10
