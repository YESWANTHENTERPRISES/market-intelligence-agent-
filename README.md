# AI Market Intelligence Terminal & DOM Module

A compact, dark, TradingView-style market intelligence Chrome Extension powered by FastAPI, WebSockets, and a deterministic multi-source scoring engine.

---

## DOM Intelligence Module & Provider Architecture

The DOM (Depth of Market) Intelligence Module aggregates real-time broker order book liquidity and depth coordinates across institutional MetaTrader 5 (MT5) and Spotware cTrader Open API feeds.

### Supported DOM Data Sources

1. **MetaTrader 5 (MT5)**:
   - **Type**: Real-time Terminal Depth of Market & Level 2 Order Book (`market_book_get`).
   - **Units**: Standard Lots.
   - **Freshness**: Real-time tick & DOM updates via local IPC.
   - **Configuration**: `MT5_ENABLED=true`, `MT5_PATH`, `MT5_LOGIN`, `MT5_PASSWORD`, `MT5_SERVER`.

2. **Spotware cTrader Open API**:
   - **Type**: Institutional & Retail Broker Market Depth (`ProtoOADepthEvent`).
   - **Units**: Standard Lots.
   - **Freshness**: Real-time Protobuf streaming.
   - **Configuration**: `CTRADER_ENABLED=true`, `CTRADER_CLIENT_ID`, `CTRADER_CLIENT_SECRET`, `CTRADER_ACCESS_TOKEN`, `CTRADER_ACCOUNT_ID`.

---

## Non-Negotiable Data Rules & Provider Limitations

### 1. Dynamic Source Coverage & Fail-Safe Handling
- The coverage indicator dynamically scales to reflect the active registered adapters: `NO-SOURCE (0/N)`, `SINGLE-SOURCE (1/N)`, or `MULTI-SOURCE (N/N)`.
- If a provider is inaccessible, unconfigured, or offline, its status returns `UNAVAILABLE` and it is excluded from aggregation.
- Source weights are dynamically renormalized across active/eligible providers only.

### 2. Relative Depth Scoring
- Each active provider's raw orderbook volume is converted into relative percentile scores (`0–100`) before applying renormalized source weights.
- Multi-source agreement elevates liquidity zone confluence without conflating different broker execution sizes.

---

## Setup & Execution

### 1. Environment Configuration
Add your API keys and optional DOM broker settings to `backend/.env`:
```env
FINNHUB_API_KEY=your_key_here
FRED_API_KEY=your_key_here
GEMINI_API_KEY=your_key_here

# MetaTrader 5 DOM Configuration (Optional)
MT5_ENABLED=false
MT5_PATH=C:\Program Files\MetaTrader 5\terminal64.exe
MT5_LOGIN=12345678
MT5_PASSWORD=your_mt5_password
MT5_SERVER=YourBroker-Server

# Spotware cTrader Open API Configuration (Optional)
CTRADER_ENABLED=false
CTRADER_CLIENT_ID=your_client_id
CTRADER_CLIENT_SECRET=your_client_secret
CTRADER_ACCESS_TOKEN=your_access_token
CTRADER_ACCOUNT_ID=1234567
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
