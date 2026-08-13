# AI Market Intelligence Terminal & DOM Module

A compact, dark, TradingView-style market intelligence Chrome Extension powered by FastAPI, WebSockets, and a deterministic multi-source scoring engine.

---

## DOM Intelligence Module & Provider Architecture

The DOM (Depth of Market) Intelligence Module aggregates liquidity, positioning, and price coordinate data across multiple institutional and OTC data feeds.

### Provider Data Sources

1. **COMEX Gold Futures (GC)**:
   - **Type**: Centralized Futures Exchange Order Book.
   - **Units**: Contracts (e.g. 100 troy oz per contract).
   - **Freshness**: 15-Minute Delayed (or Live with direct exchange credentials).
   - **Price Coordinate**: Futures Price (e.g. `$4,432.80`). Requires **Basis Normalization** (`spot_price = futures_price - basis`) to map into XAUUSD spot coordinates.

2. **Broker-Specific OTC Data (e.g. OANDA / Dukascopy)**:
   - **Type**: Decentralized Over-The-Counter (OTC) Broker Order Books & Client Sentiment.
   - **Units**: Standard Lots / Units.
   - **Freshness**: Real-time Live (0.5s–1.5s).
   - **Retail Positioning**: Aggregated retail client long vs short sentiment ratio (e.g. `64.5% LONG`).

---

## Non-Negotiable Data Rules & Provider Limitations

### 1. OTC Broker Depth vs. Centralized Futures Depth
- OTC broker depth represents retail and broker-client liquidity within a specific execution pool.
- COMEX futures depth represents centralized exchange limit orders.
- **Unit Normalization Rule**: Raw COMEX contract quantities and OTC broker units are **never directly compared**. Each provider's depth is converted into relative percentile scores (`0–100`) before applying renormalized source weights.

### 2. Spot / Futures Basis Normalization
- Futures and spot prices diverge due to carry cost, interest rates, and contract expiry (`basis = futures_mid - spot_mid`).
- The DOM module dynamically computes `basis` and subtracts it from COMEX futures limit prices before price bucketing into discrete 2-dollar spot zones.
- **Stale Basis Rejection**: If the timestamp delta between futures and spot snapshots exceeds 60 seconds, `basis` is marked `UNAVAILABLE` and un-normalized futures levels are rejected from spot aggregation.

### 3. Non-Institutional Order Labeling
- Large limit ask orders on COMEX are labeled strictly as `FUTURES SELL WALL` or `COMEX ASK LIQUIDITY`.
- **Institutional Identity Disclaimer**: The system **never asserts** that a large order is definitely "institutional", "smart money", or an "algorithm". Order intent cannot be proven from depth alone.

### 4. Production Fail-Safe State Handling
- No mock data or fake numbers are fabricated in production.
- If a provider is inaccessible or unconfigured, its state returns `UNAVAILABLE`.
- Source weights are dynamically renormalized across active/eligible providers only.

---

## Setup & Execution

### 1. Environment Configuration
Add your API keys to `backend/.env`:
```env
FINNHUB_API_KEY=your_key_here
FRED_API_KEY=your_key_here
GEMINI_API_KEY=your_key_here
HOST=0.0.0.0
PORT=8000
```

### 2. Run Tests
```powershell
$env:PYTHONPATH="backend"; python -m pytest backend/tests -v
```

### 3. Start Backend Server
Double-click `start_server.bat` or run:
```powershell
$env:PYTHONPATH="backend"; python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

### 4. Load Extension in Chrome
1. Open `chrome://extensions` in Google Chrome.
2. Enable **Developer Mode** (top-right toggle).
3. Click **Load unpacked** and select the `chrome_extension` folder.
