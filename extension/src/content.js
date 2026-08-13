// Content script injected into TradingView pages

const PANEL_WIDTH = "292px";

function injectPanelContainer() {
  if (document.getElementById("ai-intelligence-root")) return;

  const container = document.createElement("div");
  container.id = "ai-intelligence-root";
  document.body.appendChild(container);

  // Shift TradingView canvas right
  document.body.style.marginLeft = PANEL_WIDTH;
  document.body.style.transition = "margin-left 0.2s ease-in-out";

  // Load React app bundle into root
  if (typeof window.mountIntelligenceTerminal === "function") {
    window.mountIntelligenceTerminal(container);
  } else {
    const script = document.createElement("script");
    script.src = chrome.runtime.getURL("main.js");
    script.type = "module";
    document.head.appendChild(script);
  }
}

function detectSymbol() {
  let symbol = "XAUUSD";
  let tf = "5M";

  // Priority 1: URL Query / Path
  const urlParams = new URLSearchParams(window.location.search);
  if (urlParams.has("symbol")) {
    symbol = urlParams.get("symbol");
  } else {
    const pathMatch = window.location.pathname.match(/\/chart\/([^\/]+)/);
    if (pathMatch && pathMatch[1]) {
      symbol = pathMatch[1].split(":")[1] || pathMatch[1];
    }
  }

  // Priority 2: Document Title
  if (!symbol || symbol === "XAUUSD") {
    const titleMatch = document.title.match(/^([A-Z0-9]+)/);
    if (titleMatch) {
      symbol = titleMatch[1];
    }
  }

  // Clean symbol
  symbol = symbol.replace(/[^A-Za-z0-9]/g, "").toUpperCase() || "XAUUSD";

  return { symbol, timeframe: tf };
}

let lastDetected = { symbol: "", timeframe: "" };

function checkSymbolChange() {
  const current = detectSymbol();
  if (current.symbol !== lastDetected.symbol || current.timeframe !== lastDetected.timeframe) {
    lastDetected = current;
    chrome.runtime.sendMessage({
      type: "SYMBOL_CHANGED",
      symbol: current.symbol,
      timeframe: current.timeframe
    });
  }
}

// Initial injection and symbol monitor loop
injectPanelContainer();
setInterval(checkSymbolChange, 2000);

// Global Keyboard Shortcuts
document.addEventListener("keydown", (e) => {
  if (e.ctrlKey && e.shiftKey) {
    const key = e.key.toUpperCase();
    if (key === "G") {
      e.preventDefault();
      window.dispatchEvent(new CustomEvent("AI_PANEL_TOGGLE"));
    } else if (key === "R") {
      e.preventDefault();
      chrome.runtime.sendMessage({ type: "REQUEST_REFRESH" });
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
