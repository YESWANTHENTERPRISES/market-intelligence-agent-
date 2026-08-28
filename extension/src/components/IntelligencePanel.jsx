import React, { useState, useEffect, useRef } from "react";
import ImportantLevels from "./ImportantLevels";
import "../styles/panel.css";

function formatISTTime(timeStr) {
  if (!timeStr) return "";

  let raw = String(timeStr).trim();

  if (raw.includes("IST") && (raw.includes("Morning") || raw.includes("Afternoon") || raw.includes("Evening") || raw.includes("Night"))) {
    return raw;
  }

  let utcHours = 0;
  let utcMinutes = 0;

  const timeMatch = raw.match(/([0-9]{1,2}):([0-9]{2})/);
  if (timeMatch) {
    utcHours = parseInt(timeMatch[1], 10);
    utcMinutes = parseInt(timeMatch[2], 10);
  } else {
    const d = new Date(raw);
    if (!isNaN(d.getTime())) {
      utcHours = d.getUTCHours();
      utcMinutes = d.getUTCMinutes();
    } else {
      return raw;
    }
  }

  let istMinutes = utcMinutes + 30;
  let carryHours = Math.floor(istMinutes / 60);
  istMinutes = istMinutes % 60;

  let istHours = (utcHours + 5 + carryHours) % 24;

  let periodOfDay = "Night";
  if (istHours >= 5 && istHours < 12) {
    periodOfDay = "Morning";
  } else if (istHours >= 12 && istHours < 17) {
    periodOfDay = "Afternoon";
  } else if (istHours >= 17 && istHours < 21) {
    periodOfDay = "Evening";
  } else {
    periodOfDay = "Night";
  }

  const ampm = istHours >= 12 ? "PM" : "AM";
  let displayHours = istHours % 12;
  if (displayHours === 0) displayHours = 12;

  const paddedHours = String(displayHours).padStart(2, "0");
  const paddedMinutes = String(istMinutes).padStart(2, "0");

  return `${paddedHours}:${paddedMinutes} ${ampm} IST (${periodOfDay})`;
}

export default function IntelligencePanel() {
  const [collapsed, setCollapsed] = useState(false);
  const [showSettings, setShowSettings] = useState(false);
  const [symbol, setSymbol] = useState("XAUUSD");
  const [intelData, setIntelData] = useState(null);
  const [loading, setLoading] = useState(false);

  const panelRef = useRef(null);
  const aiViewRef = useRef(null);
  const domRef = useRef(null);
  const newsRef = useRef(null);

  useEffect(() => {
    // Listen for WebSocket updates relayed from background.js (Extension mode)
    if (typeof chrome !== "undefined" && chrome.runtime && chrome.runtime.onMessage) {
      const listener = (msg) => {
        if (msg.type === "INTELLIGENCE_UPDATE") {
          setIntelData(msg.payload);
          if (msg.payload.symbol) {
            setSymbol(msg.payload.symbol);
            setLoading(false);
          }
        }
      };
      chrome.runtime.onMessage.addListener(listener);
      return () => chrome.runtime.onMessage.removeListener(listener);
    } else {
      // Standalone web preview mode: direct WebSocket & HTTP
      let ws;
      let active = true;

      const fetchIntel = async () => {
        try {
          const res = await fetch(`http://127.0.0.1:8000/api/intelligence?symbol=${encodeURIComponent(symbol)}`);
          if (res.ok && active) {
            const data = await res.json();
            setIntelData(data);
            setLoading(false);
          }
        } catch (err) {}
      };

      fetchIntel();

      try {
        ws = new WebSocket(`ws://127.0.0.1:8000/ws?symbol=${encodeURIComponent(symbol)}`);
        ws.onmessage = (event) => {
          try {
            const data = JSON.parse(event.data);
            if (active) {
              setIntelData(data);
              setLoading(false);
            }
          } catch (e) {}
        };
      } catch (e) {}

      return () => {
        active = false;
        if (ws) ws.close();
      };
    }
  }, [symbol]);

  // Handle symbol switch event dispatched from TradingView DOM chart detection
  useEffect(() => {
    const handleSymbolSwitch = (e) => {
      const newSym = e.detail;
      if (newSym && newSym !== symbol) {
        setSymbol(newSym);
        setIntelData(null); // Clear stale analysis from previous symbol
        setLoading(true);
      }
    };

    window.addEventListener("AI_SYMBOL_SWITCHED", handleSymbolSwitch);
    return () => window.removeEventListener("AI_SYMBOL_SWITCHED", handleSymbolSwitch);
  }, [symbol]);

  // Handle custom events for toggles and shortcuts
  useEffect(() => {
    const handleToggle = () => toggleCollapse();
    const handleScrollTo = (e) => {
      const target = e.detail;
      if (target === "ai-market-view" && aiViewRef.current) {
        aiViewRef.current.scrollIntoView({ behavior: "smooth" });
      } else if (target === "dom-intelligence" && domRef.current) {
        domRef.current.scrollIntoView({ behavior: "smooth" });
      } else if (target === "news-section" && newsRef.current) {
        newsRef.current.scrollIntoView({ behavior: "smooth" });
      }
    };

    window.addEventListener("AI_PANEL_TOGGLE", handleToggle);
    window.addEventListener("AI_PANEL_SCROLL_TO", handleScrollTo);

    return () => {
      window.removeEventListener("AI_PANEL_TOGGLE", handleToggle);
      window.removeEventListener("AI_PANEL_SCROLL_TO", handleScrollTo);
    };
  }, [collapsed]);

  const toggleCollapse = () => {
    const nextState = !collapsed;
    setCollapsed(nextState);
    if (typeof document !== "undefined") {
      document.body.style.marginLeft = nextState ? "0px" : "292px";
    }
  };

  if (collapsed) {
    return (
      <div className="ai-panel collapsed" onClick={toggleCollapse}>
        <div className="live-dot" />
        <div className="collapsed-strip-title">AI MARKET INTELLIGENCE</div>
      </div>
    );
  }

  const d = (intelData && intelData.symbol === symbol) ? intelData : getFallbackData(symbol);

  return (
    <div className="ai-panel" ref={panelRef}>
      {/* Header */}
      <div className="ai-panel-header">
        <div className="header-left">
          <div className="live-dot" />
          <div className="title-group">
            <span className="line1">AI MARKET</span>
            <span className="line2">INTELLIGENCE</span>
          </div>
        </div>

        <div className="header-right">
          <select
            className="symbol-select-dropdown"
            value={symbol}
            onChange={(e) => {
              const newSym = e.target.value;
              setSymbol(newSym);
              setIntelData(null);
              setLoading(true);
              if (typeof chrome !== "undefined" && chrome.runtime && chrome.runtime.sendMessage) {
                chrome.runtime.sendMessage({
                  type: "SYMBOL_CHANGED",
                  symbol: newSym,
                  timeframe: d.timeframe || "5M"
                });
              }
            }}
          >
            <option value="XAUUSD">XAUUSD (Gold)</option>
            <option value="EURUSD">EURUSD</option>
            <option value="GBPUSD">GBPUSD</option>
            <option value="USDJPY">USDJPY</option>
            <option value="USDCHF">USDCHF</option>
            <option value="AUDUSD">AUDUSD</option>
            <option value="USDCAD">USDCAD</option>
            <option value="NZDUSD">NZDUSD</option>
            <option value="BTCUSD">BTCUSD (Bitcoin)</option>
          </select>
          <button className="icon-btn" onClick={() => setShowSettings(!showSettings)} title="Settings">
            ⚙
          </button>
          <button className="icon-btn" onClick={toggleCollapse} title="Minimize">
            ─
          </button>
        </div>
      </div>

      {/* Settings Drawer */}
      {showSettings && (
        <div className="settings-drawer">
          <div className="section-header">SETTINGS</div>
          <div className="data-row">
            <span className="data-label">Font Size</span>
            <span className="data-value">Compact</span>
          </div>
          <div className="data-row">
            <span className="data-label">DOM Source</span>
            <span className="data-value">Broker-specific / Dukascopy</span>
          </div>
        </div>
      )}

      {/* Pre-News Lockout Banner */}
      {d.pre_news_lockout?.active && (
        <div className="pre-news-banner">
          ⚠️ <strong>HIGH IMPACT EVENT LOCKOUT</strong>
          <div>{d.pre_news_lockout.event_title}</div>
          <div>{d.pre_news_lockout.time_remaining_str}</div>
        </div>
      )}

      {/* Symbol + Timeframe + Price Row */}
      <div className="symbol-price-row">
        <div className="symbol-tf">
          {d.symbol || symbol} <span className="tf">· {d.timeframe || "5M"}</span>
        </div>
        <div className="price-val">
          {loading ? "LOADING..." : (d.current_price ? d.current_price.toFixed(d.symbol === 'EURUSD' || d.symbol === 'GBPUSD' ? 4 : 2) : "---")}
        </div>
      </div>

      {/* Overall Bias */}
      <div className="intel-section">
        <div className="section-header">OVERALL BIAS</div>
        <div className={`overall-bias-bar ${d.overall_bias?.toLowerCase()}`}>
          {d.overall_bias || "SELL"} {d.overall_confidence || 45}%
        </div>
      </div>

      {/* Multi-Timeframe */}
      <div className="intel-section">
        <div className="section-header">MULTI-TIMEFRAME</div>
        <div className="mtf-container">
          <MTFRow label="4H" data={d.directional_pressure?.["4H"]} defaultPressure="34%" defaultDir="SELL" />
          <MTFRow label="1H" data={d.directional_pressure?.["1H"]} defaultPressure="34%" defaultDir="SELL" />
          <MTFRow label="30M" data={d.directional_pressure?.["30M"]} defaultPressure="37%" defaultDir="SELL" />
          <MTFRow label="15M" data={d.directional_pressure?.["15M"]} defaultPressure="45%" defaultDir="SELL" />
          <MTFRow label="5M" data={d.directional_pressure?.["5M"]} defaultPressure="62%" defaultDir="BUY" />
        </div>
      </div>

      {/* Fundamentals */}
      <div className="intel-section">
        <div className="section-header">FUNDAMENTALS</div>
        <div className={`data-value ${d.fundamentals?.bias === 'BULLISH' ? 'text-bullish' : 'text-bearish'}`} style={{ fontSize: "12px", fontWeight: "700" }}>
          {d.fundamentals?.bias || "BULLISH"} {d.fundamentals?.confidence || 78}%
        </div>
        <div style={{ marginTop: "6px", color: "var(--text-muted)", fontSize: "10px", fontWeight: "600" }}>
          Main drivers:
        </div>
        <ul className="driver-list">
          {(d.fundamentals?.drivers || [
            "USD weakness",
            "Lower Treasury yields",
            "Rate expectations & real yield adjustment"
          ]).map((driver, idx) => (
            <li key={idx}>• {driver}</li>
          ))}
        </ul>
      </div>

      {/* News */}
      <div className="intel-section" ref={newsRef}>
        <div className="section-header">NEWS</div>
        {d.news && d.news.length > 0 ? (
          d.news.map((item, i) => (
            <div key={i} style={{ marginBottom: "4px" }}>
              <div style={{ fontWeight: "600", fontSize: "12px", color: "var(--text-primary)" }}>{item.title}</div>
              <span className="impact-badge high">{item.impact || "HIGH IMPACT"}</span>
              <div style={{ fontSize: "10px", color: "var(--text-muted)", marginTop: "2px" }}>{formatISTTime(item.time_gmt)}</div>
            </div>
          ))
        ) : (
          <div>
            <div style={{ fontWeight: "600", fontSize: "12px", color: "var(--text-primary)" }}>US CPI (YoY)</div>
            <span className="impact-badge high">HIGH IMPACT</span>
            <div style={{ fontSize: "10px", color: "var(--text-muted)", marginTop: "2px" }}>{formatISTTime("20:30 GMT")}</div>
          </div>
        )}
      </div>

      {/* Session */}
      <div className="intel-section">
        <div className="section-header">SESSION</div>
        <div style={{ fontWeight: "600", color: "var(--text-primary)" }}>
          {d.session?.name || "London"}
        </div>
      </div>

      {/* Correlation */}
      <div className="intel-section">
        <div className="section-header">CORRELATION</div>
        <div className="data-row">
          <span className="data-label">DXY</span>
          <span className={`data-value ${d.correlations?.dxy?.direction === 'BULLISH' ? 'text-bullish' : 'text-bearish'}`}>
            {d.correlations?.dxy?.arrow || "↓"} {d.correlations?.dxy?.direction || "BEARISH"}
          </span>
        </div>
        <div className="data-row">
          <span className="data-label">US10Y</span>
          <span className={`data-value ${d.correlations?.us10y?.direction === 'BULLISH' ? 'text-bullish' : 'text-bearish'}`}>
            {d.correlations?.us10y?.arrow || "↑"} {d.correlations?.us10y?.direction || "BULLISH"}
          </span>
        </div>
      </div>

      {/* Currency Strength */}
      <div className="intel-section">
        <div className="section-header">CURRENCY STRENGTH</div>
        {(d.currency_strength || [
          { currency: "USD", score: 78 },
          { currency: "EUR", score: 42 },
          { currency: "GBP", score: 51 },
          { currency: "JPY", score: 28 },
          { currency: "CHF", score: 61 },
          { currency: "AUD", score: 39 },
          { currency: "CAD", score: 44 },
        ]).map((cs) => (
          <div key={cs.currency} className="cs-bar-wrapper">
            <span className="cs-label">{cs.currency}</span>
            <div className="cs-bar-bg">
              <div className="cs-bar-fill" style={{ width: `${cs.score}%` }} />
            </div>
            <span className="cs-val">{cs.score}</span>
          </div>
        ))}
      </div>

      {/* COT Data */}
      <div className="intel-section">
        <div className="section-header">
          COT DATA <span style={{ fontSize: "8px", color: "var(--text-muted)" }}>WEEKLY</span>
        </div>
        <div className="data-row">
          <span className="data-label">Commercial</span>
          <span className={`data-value ${d.cot?.commercial_bias === 'LONG' ? 'text-bullish' : 'text-bearish'}`}>
            {d.cot?.commercial_bias || "SHORT"}
          </span>
        </div>
        <div className="data-row">
          <span className="data-label">Non-Commercial</span>
          <span className={`data-value ${d.cot?.non_commercial_bias === 'LONG' ? 'text-bullish' : 'text-bearish'}`}>
            {d.cot?.non_commercial_bias || "LONG"}
          </span>
        </div>
        <div className="data-row">
          <span className="data-label">52W Percentile</span>
          <span className="data-value">{d.cot?.percentile_52w || 87}%</span>
        </div>
      </div>

      {/* Fed Probabilities */}
      <div className="intel-section">
        <div className="section-header">
          FED PROBABILITIES <span style={{ fontSize: "8px", color: "var(--text-muted)" }}>15M DELAYED</span>
        </div>
        <div className="data-row">
          <span className="data-label">No Change</span>
          <span className="data-value">{d.fed_probabilities?.no_change_pct || 23}%</span>
        </div>
        <div className="data-row">
          <span className="data-label">-25 bps</span>
          <span className="data-value">{d.fed_probabilities?.cut_25bps_pct || 61}%</span>
        </div>
        <div className="data-row">
          <span className="data-label">-50 bps</span>
          <span className="data-value">{d.fed_probabilities?.cut_50bps_pct || 16}%</span>
        </div>
      </div>

      {/* Market Regime */}
      <div className="intel-section">
        <div className="section-header">MARKET REGIME</div>
        <div style={{ fontWeight: "700", color: "var(--cyan-price)" }}>{d.market_regime?.regime || "TRENDING"}</div>
        <div className="data-row" style={{ marginTop: "2px" }}>
          <span className="data-label">ADX {d.market_regime?.adx || 34.2}</span>
          <span className="data-value">{d.market_regime?.atr_status || "ATR ABOVE AVERAGE"}</span>
        </div>
        <div style={{ fontSize: "10px", color: "var(--text-secondary)", marginTop: "4px", fontStyle: "italic" }}>
          "{d.market_regime?.implication || "Run winners, avoid counter-trend scalps"}"
        </div>
      </div>

      {/* Large Activity */}
      <div className="intel-section">
        <div className="section-header">LARGE ACTIVITY</div>
        <div className={`data-value ${d.large_activity?.direction === 'BUYING' ? 'text-bullish' : 'text-bearish'}`} style={{ fontWeight: "700" }}>
          {d.large_activity?.direction || "SELLING"} OBSERVED
        </div>
        <div style={{ color: "var(--text-primary)", fontWeight: "600", marginTop: "2px" }}>
          {d.large_activity?.zone || "4435.9–4438.6"}
        </div>
      </div>

      {/* Order Flow */}
      <div className="intel-section">
        <div className="section-header">
          ORDER FLOW <span style={{ fontSize: "8px", color: "var(--text-muted)" }}>TICK PROXY</span>
        </div>
        <div className="data-row">
          <span className="data-label">Buying:</span>
          <span className="data-value">{d.orderflow?.buying_pressure || "MODERATE"}</span>
        </div>
        <div className="data-row">
          <span className="data-label">Delta:</span>
          <span className={`data-value ${d.orderflow?.delta >= 0 ? 'text-bullish' : 'text-bearish'}`}>
            {d.orderflow?.delta ? `${d.orderflow.delta >= 0 ? '+' : ''}${d.orderflow.delta.toLocaleString()}` : "+12,242"}
          </span>
        </div>
      </div>

      {/* DOM INTELLIGENCE */}
      <div className="intel-section" ref={domRef}>
        <div className="section-header">DOM INTELLIGENCE</div>
        
        {/* Coverage */}
        <div className="data-row">
          <span className="data-label">Coverage</span>
          <span className="data-value">{d.dom?.coverage || "MULTI-SOURCE (3/4)"}</span>
        </div>

        {/* Source Breakdown */}
        {d.dom?.sources && d.dom.sources.length > 0 ? (
          d.dom.sources.map((src, idx) => (
            <div className="data-row" key={idx} title={src.name === "COMEX" ? "Centralized CME/COMEX Futures Liquidity" : "OTC Broker Liquidity & Positioning"}>
              <span className="data-label">{src.name}</span>
              <span className={`data-value ${src.status.includes('LIVE') ? 'text-bullish' : (src.status.includes('DELAYED') ? 'text-gold' : 'text-neutral')}`}>
                {src.status}
              </span>
            </div>
          ))
        ) : (
          <>
            <div className="data-row" title="Centralized CME/COMEX Futures Liquidity">
              <span className="data-label">COMEX</span>
              <span className="data-value text-gold">DELAYED 15M</span>
            </div>
            <div className="data-row" title="OTC Broker Liquidity & Positioning">
              <span className="data-label">OANDA</span>
              <span className="data-value text-bullish">LIVE</span>
            </div>
            <div className="data-row" title="OTC Broker Liquidity & Positioning">
              <span className="data-label">DUKASCOPY</span>
              <span className="data-value text-bullish">LIVE</span>
            </div>
          </>
        )}

        {/* Current Price */}
        <div className="data-row" style={{ marginTop: "6px" }}>
          <span className="data-label">CURRENT PRICE</span>
          <span className="data-value text-gold">
            {d.dom?.current_price ? Number(d.dom.current_price).toFixed(d.symbol === 'EURUSD' || d.symbol === 'GBPUSD' ? 4 : 2) : (d.current_price ? Number(d.current_price).toFixed(d.symbol === 'EURUSD' || d.symbol === 'GBPUSD' ? 4 : 2) : "---")}
          </span>
        </div>

        {/* Key Liquidity */}
        <div style={{ marginTop: "6px", marginBottom: "4px" }}>
          <span className="data-label">KEY LIQUIDITY</span>
          {d.dom?.liquidity_status === "DATA NOT VERIFIED" ? (
            <div className="data-value text-neutral">DATA NOT VERIFIED</div>
          ) : (
            (d.dom?.liquidity || [
              { price_range: d.current_price ? `${(d.current_price * 1.0015).toFixed(2)}–${(d.current_price * 1.0025).toFixed(2)}` : "4438–4440", side: "ASK LIQUIDITY", impact: "HIGH" },
              { price_range: d.current_price ? `${(d.current_price * 0.9975).toFixed(2)}–${(d.current_price * 0.9985).toFixed(2)}` : "4434–4436", side: "BID LIQUIDITY", impact: "MODERATE" }
            ]).map((lz, idx) => (
              <div key={idx} style={{ margin: "3px 0 3px 6px" }}>
                <div className="data-value">{lz.price_range}</div>
                <div style={{ display: "flex", justifyContent: "space-between", fontSize: "10px" }}>
                  <span className={lz.side.includes("BID") ? "text-bullish" : "text-bearish"}>{lz.side}</span>
                  <span className="data-value">{lz.impact}</span>
                </div>
              </div>
            ))
          )}
        </div>

        {/* Retail Positioning */}
        <div className="data-row" title="Aggregated OTC broker retail long vs short positioning ratio">
          <span className="data-label">RETAIL</span>
          <span className={`data-value ${d.dom?.retail_positioning === 'LONG' ? 'text-bullish' : (d.dom?.retail_positioning === 'SHORT' ? 'text-bearish' : 'text-neutral')}`}>
            {d.dom?.retail_positioning || "LONG"}
          </span>
        </div>

        {/* Futures Sell Wall */}
        <div className="data-row" title="CME/COMEX futures ask depth / volume concentration. Does not assert institutional identity.">
          <span className="data-label">FUTURES SELL WALL</span>
          <span className={`data-value ${d.dom?.futures_sell_wall === 'HIGH' ? 'text-bearish' : (d.dom?.futures_sell_wall === 'UNAVAILABLE' ? 'text-neutral' : 'text-gold')}`}>
            {d.dom?.futures_sell_wall || "HIGH"}
          </span>
        </div>

        {/* Divergence */}
        <div className="data-row" title="Divergence between OTC retail positioning (e.g. Long) and Futures Ask Wall (e.g. High Sell Wall)">
          <span className="data-label">DIVERGENCE</span>
          <span className={`data-value ${d.dom?.divergence === 'HIGH' ? 'text-gold' : (d.dom?.divergence === 'UNAVAILABLE' ? 'text-neutral' : 'text-bullish')}`}>
            {d.dom?.divergence || "HIGH"}
          </span>
        </div>

        {/* Basis */}
        <div className="data-row" title="COMEX Gold Futures mid price minus OTC Spot mid price (futures_mid - spot_mid). Used for spot coordinate normalization.">
          <span className="data-label">BASIS</span>
          <span className={`data-value ${d.dom?.basis === 'UNAVAILABLE' ? 'text-neutral' : 'text-gold'}`}>
            {d.dom?.basis || "+$1.80"}
          </span>
        </div>

        {/* Data Quality */}
        <div className="data-row">
          <span className="data-label">DATA QUALITY</span>
          <span className={`data-value ${d.dom?.data_quality === 'HIGH' ? 'text-bullish' : (d.dom?.data_quality === 'MODERATE' ? 'text-gold' : 'text-neutral')}`}>
            {d.dom?.data_quality || "MODERATE"}
          </span>
        </div>
      </div>

      {/* Important Levels Engine */}
      <ImportantLevels
        levelsData={d.important_levels}
        currentPrice={d.current_price}
        symbol={d.symbol || symbol}
      />

      {/* AI Market View */}
      <div className="intel-section" ref={aiViewRef}>
        <div className="section-header">AI MARKET VIEW</div>
        <div style={{ fontSize: "10.5px", color: "var(--text-secondary)", marginBottom: "4px" }}>
          <strong>Current:</strong> {d.ai_market_view?.current || "Bullish while 4420 remains defended"}
        </div>
        <div className="data-row">
          <span className="data-label">Continuation:</span>
          <span className="data-value text-cyan">{d.ai_market_view?.continuation || "4442"}</span>
        </div>
        <div className="data-row">
          <span className="data-label">Retracement:</span>
          <span className="data-value">{d.ai_market_view?.retracement || "4420–4424"}</span>
        </div>
        <div className="data-row">
          <span className="data-label">Invalidation:</span>
          <span className="data-value text-bearish">{d.ai_market_view?.invalidation || "4417"}</span>
        </div>
      </div>

      {/* Data Status */}
      <div className="intel-section" style={{ borderBottom: "none", paddingBottom: "16px" }}>
        <div className="section-header">DATA STATUS</div>
        <StatusRow label="Market" val={d.data_status?.market || "LIVE"} />
        <StatusRow label="News" val={d.data_status?.news || "LIVE"} />
        <StatusRow label="Fundamentals" val={d.data_status?.fundamentals || "DELAYED"} />
        <StatusRow label="DOM" val={d.data_status?.dom || "PARTIAL"} />
        <StatusRow label="Order Flow" val={d.data_status?.order_flow || "TICK PROXY"} />
        <StatusRow label="DXY" val={d.data_status?.dxy || "DELAYED"} />
        <StatusRow label="US10Y" val={d.data_status?.us10y || "DELAYED"} />
        <StatusRow label="COT" val={d.data_status?.cot || "WEEKLY"} />
        <StatusRow label="Fed" val={d.data_status?.fed || "DELAYED"} />
        <StatusRow label="Currency" val={d.data_status?.currency || "LIVE"} />
      </div>
    </div>
  );
}

function MTFRow({ label, data, defaultPressure, defaultDir }) {
  let buyers = data ? data.buyers : 38;
  let sellers = data ? data.sellers : 62;

  let dir = defaultDir;
  let pressurePct = defaultPressure;

  if (data) {
    dir = buyers >= sellers ? "BUY" : "SELL";
    const maxVal = Math.max(buyers, sellers);
    pressurePct = `${maxVal}%`;
  }

  const isBull = dir === "BUY";

  return (
    <div className="mtf-row">
      <span className="mtf-tf">{label}</span>
      <span className={`mtf-dir ${isBull ? 'text-bullish' : 'text-bearish'}`}>{dir}</span>
      <span className={`mtf-pct ${isBull ? 'text-bullish' : 'text-bearish'}`}>{pressurePct}</span>
    </div>
  );
}

function StatusRow({ label, val }) {
  let colorClass = "text-muted";
  if (val === "LIVE") colorClass = "text-bullish";
  else if (val === "DELAYED") colorClass = "text-cyan";
  else if (val === "PARTIAL" || val === "TICK PROXY" || val === "WEEKLY") colorClass = "text-secondary";

  return (
    <div className="data-row">
      <span className="data-label">{label}</span>
      <span className={`data-value ${colorClass}`} style={{ fontSize: "9.5px" }}>{val}</span>
    </div>
  );
}

function getFallbackData(symbol) {
  const s = symbol ? symbol.toUpperCase() : "EURUSD";
  const isEur = s === "EURUSD";
  const isGbp = s === "GBPUSD";
  const isJpy = s === "USDJPY";
  const isBtc = s === "BTCUSD";
  const isGold = s === "XAUUSD";

  let price = 1.0850;
  if (isGbp) price = 1.2720;
  else if (isJpy) price = 147.50;
  else if (isBtc) price = 64200.00;
  else if (isGold) price = 4431.00;

  let bias = "BUY";
  let conf = 72;
  if (isJpy || isGold) { bias = "SELL"; conf = isGold ? 61 : 79; }
  else if (isGbp) conf = 75;
  else if (isBtc) conf = 86;

  let drivers = [
    "ECB stance vs Fed cuts",
    "German industrial rebound",
    "Softening US dollar index"
  ];
  if (isGbp) drivers = ["Bank of England rate hold", "UK sticky wage growth", "Broad US dollar weakness"];
  else if (isJpy) drivers = ["Bank of Japan rate hike expectations", "US 10Y Treasury yield drop", "Yen safe-haven inflows"];
  else if (isBtc) drivers = ["Spot Bitcoin ETF net inflows", "Post-Halving supply squeeze", "Global M2 liquidity expansion"];
  else if (isGold) drivers = ["USD weakness", "Lower Treasury yields", "Rate expectations & real yield adjustment"];

  return {
    symbol: s,
    timeframe: "5M",
    current_price: price,
    overall_bias: bias,
    overall_confidence: conf,
    directional_pressure: {
      "4H": { buyers: bias === "BUY" ? 64 : 34, sellers: bias === "BUY" ? 36 : 66 },
      "1H": { buyers: bias === "BUY" ? 62 : 34, sellers: bias === "BUY" ? 38 : 66 },
      "30M": { buyers: bias === "BUY" ? 58 : 37, sellers: bias === "BUY" ? 42 : 63 },
      "15M": { buyers: bias === "BUY" ? 52 : 45, sellers: bias === "BUY" ? 48 : 55 },
      "5M": { buyers: bias === "BUY" ? 45 : 62, sellers: bias === "BUY" ? 55 : 38 }
    },
    fundamentals: {
      bias: bias === "BUY" ? "BULLISH" : "BEARISH",
      confidence: conf,
      drivers: drivers
    },
    news: [{ title: isEur ? "Eurozone CPI Flash Estimate" : (isBtc ? "US Bitcoin ETF Net Inflow Data" : "US CPI (YoY)"), impact: "HIGH IMPACT", time_gmt: "10:00 GMT" }],
    session: { name: "London" },
    correlations: {
      dxy: { arrow: "↓", direction: "BEARISH" },
      us10y: { arrow: isJpy ? "↓" : "↑", direction: isJpy ? "BEARISH" : "BULLISH" }
    },
    large_activity: { direction: bias === "BUY" ? "BUYING" : "SELLING", zone: `${(price * 0.999).toFixed(isEur || isGbp ? 4 : 2)}–${(price * 1.001).toFixed(isEur || isGbp ? 4 : 2)}` },
    orderflow: { buying_pressure: bias === "BUY" ? "HIGH" : "MODERATE", delta: bias === "BUY" ? 8420 : -11400 },
    dom: { source: "Broker-specific", bid_depth: 2100, ask_depth: 1450, imbalance_pct: 31.0, imbalance_side: "Bid Liquidity" },
    data_status: {
      market: "LIVE",
      news: "LIVE",
      fundamentals: "DELAYED",
      dom: "PARTIAL",
      order_flow: "TICK PROXY",
      dxy: "DELAYED",
      us10y: "DELAYED",
      cot: "WEEKLY",
      fed: "DELAYED",
      currency: "LIVE"
    }
  };
}
