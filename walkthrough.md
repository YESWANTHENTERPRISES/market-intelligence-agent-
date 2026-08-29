# DOM Intelligence Module: MetaTrader 5 & cTrader Swap Walkthrough

## Summary of Changes

We completed a surgical swap of the Depth of Market (DOM) Intelligence module from legacy placeholder sources to **MetaTrader 5 (MT5)** and **Spotware cTrader Open API**.

---

### Key Architectural & Implementation Changes

1. **DOM Adapters (`backend/app/providers/dom/adapters.py`)**:
   - **`MT5DOMAdapter`**:
     - Defensive import (`try: import MetaTrader5 as mt5 ... except ImportError: MT5_AVAILABLE = False`).
     - Initialization via `mt5.initialize(path=..., login=..., password=..., server=...)`.
     - Subscribes to Level 2 DOM depth via `mt5.market_book_add()` and fetches books via `mt5.market_book_get()`.
     - Maps `BOOK_TYPE_BUY` and `BOOK_TYPE_SELL` levels directly into normalized `PriceLevel` entries.
     - Fetches top-of-book spot price via `mt5.symbol_info_tick()`.
     - Fail-safe isolation: If `MT5_AVAILABLE is False`, `MT5_ENABLED is False`, or connection fails, returns `status=SourceStatus.UNAVAILABLE` with `included_in_aggregation=False`. Never raises an unhandled exception.
   - **`CTraderDOMAdapter`**:
     - Background thread-safe depth cache (`_depth_cache`, `_lock`, `update_cached_depth`).
     - Non-blocking async retrieval via `fetch_snapshot()`.
     - Validates freshness: Returns `status=LIVE` if updated within 10s; otherwise gracefully marks depth `STALE` or `UNAVAILABLE`.
     - Fail-safe isolation: If `CTRADER_ENABLED is False` or tokens are unconfigured, cleanly returns `status=SourceStatus.UNAVAILABLE`.

2. **DOM Engine & Coverage (`backend/app/providers/dom/engine.py` & `backend/app/providers/dom/aggregator.py`)**:
   - Replaced legacy adapters with `[MT5DOMAdapter(), CTraderDOMAdapter()]`.
   - Dynamic coverage denominator derived directly from registered adapters: `len(self.adapters)`.
   - Coverage formatted dynamically: `NO-SOURCE (0/2)`, `SINGLE-SOURCE (1/2)`, `MULTI-SOURCE (2/2)`.
   - Source weights dynamically configured to `DEFAULT_SOURCE_WEIGHTS = {"MT5": 0.50, "CTRADER": 0.50}` and renormalized across active adapters.

3. **Configuration & Dependencies (`backend/app/core/config.py` & `backend/requirements.txt`)**:
   - Added `MT5_ENABLED`, `MT5_PATH`, `MT5_LOGIN`, `MT5_PASSWORD`, `MT5_SERVER`, `MT5_TIMEOUT`, `MT5_PORTABLE`, `MT5_SYMBOL_MAP`.
   - Added `CTRADER_ENABLED`, `CTRADER_CLIENT_ID`, `CTRADER_CLIENT_SECRET`, `CTRADER_ACCESS_TOKEN`, `CTRADER_ACCOUNT_ID`, `CTRADER_HOST`, `CTRADER_PORT`, `CTRADER_SYMBOL_MAP`.
   - Added `MetaTrader5`, `protobuf`, `twisted` to `backend/requirements.txt`.

4. **Extension UI Labels (`extension/src/components/IntelligencePanel.jsx` & `extension/src/components/ImportantLevels.jsx`)**:
   - Updated DOM source badges and fallback labels to display `MT5` and `cTrader`.
   - Replaced legacy source combinations with `MT5 + cTrader`.

5. **Documentation & Traceability (`README.md` & `KNOWN_GAPS.md`)**:
   - Documented MT5 and cTrader DOM configurations.
   - Updated `KNOWN_GAPS.md` with explicit fail-safe status tracking when broker terminals/tokens are unconfigured.

---

## Verification & Test Results

### 1. Dedicated MT5 & cTrader Tests (`backend/tests/test_dom_mt5_ctrader.py`)
- `test_both_adapters_disabled_no_credentials`: Verified `NO-SOURCE (0/2)` coverage, `DATA NOT VERIFIED` status, all sources `UNAVAILABLE`.
- `test_mt5_adapter_import_error_or_missing_terminal`: Verified graceful degradation on import or initialization errors.
- `test_mt5_adapter_live_book_retrieval`: Verified live L2 book extraction and price normalization.
- `test_ctrader_adapter_missing_credentials_and_live_cache`: Verified thread-safe depth cache, live status, and stale threshold decay.
- `test_dynamic_source_coverage_combinations`: Verified `SINGLE-SOURCE (1/2)` and `MULTI-SOURCE (2/2)` coverage strings.

### 2. Full Test Suite Execution
```powershell
$env:PYTHONPATH="backend"; python -m pytest backend/tests -v
```
**Result**: **225 passed, 0 failed in 149.42s** (exceeding initial 224 baseline).

### 3. Legacy Reference Audit
```powershell
grep -ri oanda backend/ chrome_extension/ extension/ README.md
```
**Result**: **0 occurrences**. All legacy references completely replaced with MT5 and cTrader.
