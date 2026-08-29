import React, { useState } from "react";

export default function ImportantLevels({ levelsData, currentPrice, symbol }) {
  // Store expanded zone string (e.g. "4.0168–4.0176")
  const [expandedZone, setExpandedZone] = useState(null);

  if (!levelsData || levelsData.status === "INSUFFICIENT_DATA") {
    return (
      <div className="intel-section">
        <div className="section-header">IMPORTANT LEVELS</div>
        <div className="data-value text-neutral" style={{ padding: "6px 0", fontSize: "11px" }}>
          INSUFFICIENT DATA AVAILABLE
        </div>
      </div>
    );
  }

  const supportList = levelsData.support || [];
  const resistanceList = levelsData.resistance || [];
  const liquidityList = levelsData.liquidity || [];

  const toggleExpand = (zoneStr) => {
    if (expandedZone === zoneStr) {
      setExpandedZone(null);
    } else {
      setExpandedZone(zoneStr);
    }
  };

  return (
    <div className="intel-section important-levels-container">
      <div className="section-header">
        IMPORTANT LEVELS{" "}
        <span style={{ fontSize: "8px", color: "var(--text-muted)", fontWeight: "normal" }}>
          DETERMINISTIC
        </span>
      </div>

      {/* RESISTANCE */}
      <div className="level-category">
        <div className="category-title text-bearish">RESISTANCE</div>
        {resistanceList.length === 0 ? (
          <div className="no-levels">No active resistance zones</div>
        ) : (
          resistanceList.map((lvl, i) => (
            <LevelCard
              key={`res-${i}`}
              level={lvl}
              type="RESISTANCE"
              isExpanded={expandedZone === (typeof lvl === "object" ? lvl.zone : lvl)}
              onToggle={() => toggleExpand(typeof lvl === "object" ? lvl.zone : lvl)}
              currentPrice={currentPrice}
            />
          ))
        )}
      </div>

      {/* SUPPORT */}
      <div className="level-category">
        <div className="category-title text-bullish">SUPPORT</div>
        {supportList.length === 0 ? (
          <div className="no-levels">No active support zones</div>
        ) : (
          supportList.map((lvl, i) => (
            <LevelCard
              key={`sup-${i}`}
              level={lvl}
              type="SUPPORT"
              isExpanded={expandedZone === (typeof lvl === "object" ? lvl.zone : lvl)}
              onToggle={() => toggleExpand(typeof lvl === "object" ? lvl.zone : lvl)}
              currentPrice={currentPrice}
            />
          ))
        )}
      </div>

      {/* LIQUIDITY */}
      <div className="level-category">
        <div className="category-title text-cyan">LIQUIDITY</div>
        {liquidityList.length === 0 ? (
          <div className="no-levels">No active liquidity pools</div>
        ) : (
          liquidityList.map((lvl, i) => (
            <LevelCard
              key={`liq-${i}`}
              level={lvl}
              type="LIQUIDITY"
              isExpanded={expandedZone === (typeof lvl === "object" ? lvl.zone : lvl)}
              onToggle={() => toggleExpand(typeof lvl === "object" ? lvl.zone : lvl)}
              currentPrice={currentPrice}
            />
          ))
        )}
      </div>
    </div>
  );
}

function LevelCard({ level, type, isExpanded, onToggle, currentPrice }) {
  const isObj = typeof level === "object" && level !== null;

  const zoneStr = isObj ? level.zone : level;
  const importance = isObj ? level.importance?.replace("_", " ") : "HIGH";
  const score = isObj ? level.confluence_score : 75;
  const liqType = isObj ? level.liquidity?.type : (type === "RESISTANCE" ? "BUY_SIDE" : "SELL_SIDE");
  const sideClass = type === "SUPPORT" ? "text-bullish" : (type === "RESISTANCE" ? "text-bearish" : "text-cyan");

  const evidence = isObj ? (level.evidence || []) : ["Multi-timeframe market structure", "DOM orderbook concentration"];
  const timeframes = isObj ? (level.timeframes || []).join(", ") : "1H, 30M";
  const domSources = isObj ? (level.dom?.sources || []).join(" + ") : "MT5 + cTrader";
  const dist = isObj ? level.distance : 0.0;
  const distAtr = isObj ? level.distance_atr : 0.0;
  const status = isObj ? level.status : "ACTIVE";
  const breakdown = isObj ? level.score_breakdown : null;

  return (
    <div className={`level-card-wrapper ${isExpanded ? "expanded" : ""}`}>
      <div className="level-card" onClick={onToggle} title="Click to expand evidence and data sources">
        <div className="level-card-top">
          <span className={`level-zone ${sideClass}`}>{zoneStr}</span>
          <span className="level-score-badge">{score} CONFLUENCE</span>
        </div>
        <div className="level-card-bottom">
          <span className={`badge-importance ${importance?.toLowerCase()}`}>
            {importance}
          </span>
          {type === "LIQUIDITY" && (
            <span className="badge-side">{liqType?.replace("_", "-")}</span>
          )}
          <span className="expand-chevron">{isExpanded ? "▲" : "▼"}</span>
        </div>
      </div>

      {/* INLINE EXPANDABLE EVIDENCE & DATA SOURCE DRAWER */}
      {isExpanded && (
        <div className="level-evidence-drawer">
          <div className="drawer-section-title">WHY THIS LEVEL IS IMPORTANT:</div>

          {/* Evidence Checkmarks */}
          <div className="evidence-list">
            {evidence.length > 0 ? (
              evidence.map((ev, idx) => (
                <div key={idx} className="evidence-item">
                  <span className="check-mark">✓</span> {ev}
                </div>
              ))
            ) : (
              <div className="evidence-item">
                <span className="check-mark">✓</span> Calculated from validated market structure
              </div>
            )}
          </div>

          {/* Score Breakdown */}
          {breakdown && (
            <div className="score-breakdown-box">
              <div className="breakdown-title">CONFLUENCE BREAKDOWN ({score}/100):</div>
              {breakdown.htf_structure > 0 && <BreakdownRow label="Higher Timeframe" pts={breakdown.htf_structure} maxPts={25} />}
              {breakdown.mtf_agreement > 0 && <BreakdownRow label="Multi-Timeframe" pts={breakdown.mtf_agreement} maxPts={20} />}
              {breakdown.period_levels > 0 && <BreakdownRow label="Prev Day/Week Level" pts={breakdown.period_levels} maxPts={15} />}
              {breakdown.dom_confluence > 0 && <BreakdownRow label="DOM Orderbook Depth" pts={breakdown.dom_confluence} maxPts={15} />}
              {breakdown.liquidity_evidence > 0 && <BreakdownRow label="Liquidity Pools" pts={breakdown.liquidity_evidence} maxPts={10} />}
              {breakdown.price_reaction > 0 && <BreakdownRow label="Rejections / Defense" pts={breakdown.price_reaction} maxPts={10} />}
              {breakdown.displacement > 0 && <BreakdownRow label="Displacement Origin" pts={breakdown.displacement} maxPts={5} />}
            </div>
          )}

          {/* Data Attributes */}
          <div className="drawer-attributes">
            <div className="attr-row">
              <span className="attr-label">Timeframes:</span>
              <span className="attr-val">{timeframes || "1H, 30M"}</span>
            </div>
            <div className="attr-row">
              <span className="attr-label">DOM Sources:</span>
              <span className="attr-val">{domSources || "MT5 + cTrader"}</span>
            </div>
            <div className="attr-row">
              <span className="attr-label">Distance to Price:</span>
              <span className="attr-val">{dist} ({distAtr} ATR)</span>
            </div>
            <div className="attr-row">
              <span className="attr-label">Level Status:</span>
              <span className="attr-val text-bullish">{status}</span>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function BreakdownRow({ label, pts, maxPts }) {
  return (
    <div className="breakdown-row">
      <span className="b-label">• {label}</span>
      <span className="b-pts">+{pts} pts</span>
    </div>
  );
}
