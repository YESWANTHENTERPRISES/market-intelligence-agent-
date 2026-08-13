import React from "react";
import ReactDOM from "react-dom/client";
import IntelligencePanel from "./components/IntelligencePanel";
import "./styles/panel.css";

const PANEL_WIDTH = "292px";

function injectPanelContainer() {
  if (document.getElementById("ai-intelligence-root")) return;

  const container = document.createElement("div");
  container.id = "ai-intelligence-root";
  document.body.appendChild(container);

  // Shift TradingView canvas right
  document.body.style.marginLeft = PANEL_WIDTH;
  document.body.style.transition = "margin-left 0.2s ease-in-out";

  // Directly render React terminal into root container
  const root = ReactDOM.createRoot(container);
  root.render(
    <React.StrictMode>
      <IntelligencePanel />
    </React.StrictMode>
  );
}

function extractSymbolText(text) {
  if (!text) return null;
  let s = text.trim();
  if (s.includes(":")) {
    s = s.split(":")[1];
  }
  const firstWord = s.split(" ")[0].split("·")[0].split("-")[0];
  const cleaned = firstWord.replace(/[^A-Za-z0-9]/g, "").toUpperCase();
  if (cleaned.length >= 3 && cleaned.length <= 10) {
    return cleaned;
  }
  return null;
}

function isReasonablePriceForSymbol(symbol, price) {
  if (!price || isNaN(price) || price <= 0) return false;
  const sym = symbol ? symbol.toUpperCase() : "";
  if (sym.includes("XAU") || sym.includes("GOLD")) {
    return price > 3500 && price < 5500;
  }
  if (sym.includes("BTC") || sym.includes("BITCOIN")) {
    return price > 20000 && price < 200000;
  }
  if (sym.includes("JPY")) {
    return price > 100 && price < 250;
  }
  if (sym.includes("EUR") || sym.includes("GBP") || sym.includes("AUD") || sym.includes("NZD") || sym.includes("CAD") || sym.includes("CHF")) {
    return price > 0.50 && price < 2.0;
  }
  return price > 0.0001;
}

function detectPrice(symbol) {
  // Query specific TradingView DOM Elements for the main chart series close/last price
  const selectors = [
    '.js-symbol-last',
    '[data-name="legend-series-item"] [class*="value-"]',
    '[class*="last-"][class*="value-"]',
    '[class*="price-"][class*="value-"]',
    '[class*="legend-"] [class*="value-"]'
  ];

  for (const sel of selectors) {
    const elements = document.querySelectorAll(sel);
    for (const el of elements) {
      if (el && el.textContent) {
        const text = el.textContent.replace(/,/g, "").trim();
        if (/^[0-9]+[hmdw]$/i.test(text) || text.includes("%")) continue;
        const numMatch = text.match(/([0-9]+(?:\.[0-9]+)?)/);
        if (numMatch && numMatch[1]) {
          const parsed = parseFloat(numMatch[1]);
          if (isReasonablePriceForSymbol(symbol, parsed)) {
            return parsed;
          }
        }
      }
    }
  }
  return null;
}

let lastDetected = { symbol: "", timeframe: "", price: null };

function detectSymbol() {
  let detected = null;
  let tf = "5M";

  // Priority 1: URL Query / Path
  const urlParams = new URLSearchParams(window.location.search);
  if (urlParams.has("symbol")) {
    detected = extractSymbolText(urlParams.get("symbol"));
  }

  if (!detected) {
    const pathMatch = window.location.pathname.match(/\/chart\/([^\/]+)/);
    if (pathMatch && pathMatch[1]) {
      detected = extractSymbolText(pathMatch[1]);
    }
  }

  // Priority 2: Document Title (e.g. "EURUSD 5m Chart — TradingView")
  if (!detected && document.title) {
    detected = extractSymbolText(document.title);
  }

  // Priority 3: TradingView DOM Header / Symbol elements
  if (!detected) {
    const symbolEl = document.querySelector('button[id*="header-toolbar-symbol-search"]') ||
                     document.querySelector('#header-toolbar-symbol-search') ||
                     document.querySelector('.js-symbol-short-name') ||
                     document.querySelector('[class*="symbolTitle-"]') ||
                     document.querySelector('[data-name="legend-series-item"]');
    if (symbolEl && symbolEl.textContent) {
      detected = extractSymbolText(symbolEl.textContent);
    }
  }

  // If no symbol detected on this frame, preserve lastDetected symbol to avoid accidental fallback flip
  if (!detected) {
    detected = lastDetected.symbol ? lastDetected.symbol : "EURUSD";
  }

  const price = detectPrice(detected);

  return { symbol: detected, timeframe: tf, price };
}

function checkSymbolChange() {
  const current = detectSymbol();
  const symbolChanged = current.symbol && current.symbol !== lastDetected.symbol;
  const priceChanged = current.price && Math.abs((current.price || 0) - (lastDetected.price || 0)) > 0.0001;

  if (symbolChanged || priceChanged) {
    lastDetected = current;
    
    if (symbolChanged) {
      // Dispatch local symbol switch event to React panel
      window.dispatchEvent(new CustomEvent("AI_SYMBOL_SWITCHED", { detail: current.symbol }));
    }

    // Send update to background service worker
    if (typeof chrome !== "undefined" && chrome.runtime && chrome.runtime.sendMessage) {
      chrome.runtime.sendMessage({
        type: "SYMBOL_CHANGED",
        symbol: current.symbol,
        timeframe: current.timeframe,
        price: current.price
      }).catch(() => {});
    }
  }
}

// Hook into History API for instant SPA navigation detection
const originalPushState = history.pushState;
history.pushState = function () {
  originalPushState.apply(this, arguments);
  setTimeout(checkSymbolChange, 50);
  setTimeout(checkSymbolChange, 500);
};

const originalReplaceState = history.replaceState;
history.replaceState = function () {
  originalReplaceState.apply(this, arguments);
  setTimeout(checkSymbolChange, 50);
  setTimeout(checkSymbolChange, 500);
};

window.addEventListener("popstate", () => {
  setTimeout(checkSymbolChange, 50);
  setTimeout(checkSymbolChange, 500);
});

// Initial injection
if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", () => {
    injectPanelContainer();
    checkSymbolChange();
  });
} else {
  injectPanelContainer();
  checkSymbolChange();
}

setInterval(checkSymbolChange, 1000);

// Global Keyboard Shortcuts
document.addEventListener("keydown", (e) => {
  if (e.ctrlKey && e.shiftKey) {
    const key = e.key.toUpperCase();
    if (key === "G") {
      e.preventDefault();
      window.dispatchEvent(new CustomEvent("AI_PANEL_TOGGLE"));
    } else if (key === "R") {
      e.preventDefault();
      if (typeof chrome !== "undefined" && chrome.runtime && chrome.runtime.sendMessage) {
        chrome.runtime.sendMessage({ type: "REQUEST_REFRESH" });
      }
    } else if (key === "S" || key === "A") {
      e.preventDefault();
      window.dispatchEvent(new CustomEvent("AI_PANEL_SCROLL_TO", { detail: "ai-market-view" }));
    } else if (key === "D") {
      e.preventDefault();
      window.dispatchEvent(new CustomEvent("AI_PANEL_SCROLL_TO", { detail: "dom-intelligence" }));
    } else if (key === "N") {
      e.preventDefault();
      window.dispatchEvent(new CustomEvent("AI_PANEL_SCROLL_TO", { detail: "news-section" }));
    }
  }
});
