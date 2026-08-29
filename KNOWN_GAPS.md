# Known Data Gaps & Upstream Provider Roadmap

This document explicitly catalogs data integrations and optional provider states in `market-intelligence-agent-`. Under the system's production integrity contract, **no fabricated numbers may masquerade as LIVE data**.

---

## 1. Broker Depth of Market (MetaTrader 5 & cTrader Open API)
- **Current Status**: `UNAVAILABLE` when `MT5_ENABLED=false` and `CTRADER_ENABLED=false` (or terminal/tokens unconfigured).
- **Impacted Fields**: `dom.coverage`, `dom.sources[MT5]`, `dom.sources[CTRADER]`, `dom.liquidity`
- **Supported Integrations**:
  - **MetaTrader 5**: Local terminal IPC connection via `MetaTrader5` package (`market_book_get` Level 2 depth).
  - **Spotware cTrader Open API**: Real-time Protobuf/WebSocket market depth streaming (`ProtoOADepthEvent`).
- **Fail-Safe Behavior**:
  - Automatically degrades to `NO-SOURCE (0/2)` coverage with `included_in_aggregation=False` when broker credentials or terminals are absent.

---

## 2. CFTC Commitment of Traders (COT Data)
- **Current Status**: `UNAVAILABLE`
- **Impacted Fields**: `cot.commercial_bias`, `cot.non_commercial_bias`, `cot.percentile_52w`
- **Target Real Data Source**: CFTC Public Disaggregated / Legacy Reports (`cftc.gov/dea/futures/deacmelf.txt`) or FRED COT series.
- **Reason Left as Placeholder**:
  - CFTC COT reports are released once weekly on Fridays at 3:30 PM EST. In this pass, to avoid asserting hardcoded 87% percentiles, the field returns `status="UNAVAILABLE"` until the weekly CFTC report ingestion pipeline is configured.

---

## 3. Fed Funds Probabilities
- **Current Status**: `UNAVAILABLE`
- **Impacted Fields**: `fed_probabilities.no_change_pct`, `fed_probabilities.cut_25bps_pct`, `fed_probabilities.cut_50bps_pct`
- **Target Real Data Source**: CME FedWatch 30-Day Fed Funds Futures (ZQ) Pricing API or FRED implied policy rate series.
- **Reason Left as Placeholder**:
  - Direct CME FedWatch probability distribution API is behind CME proprietary licensing. Field is honestly marked `status="UNAVAILABLE"` with zeroed probabilities rather than asserting frozen numbers.

---

## 4. Economic News & Calendar Feed
- **Current Status**: `LIVE` when `FINNHUB_API_KEY` is provided; `UNAVAILABLE` (empty list `[]`) when key is absent.
- **Impacted Fields**: `news`, `pre_news_lockout`, `data_status.news`
- **Target Real Data Source**: Finnhub Forex/Economic Calendar API (`/api/v1/news?category=forex` or `/api/v1/calendar/economic`).
- **Reason**:
  - Users without an API key will see `news=[]` and `data_status.news="UNAVAILABLE"`, preventing stale static headlines from appearing as fresh.
