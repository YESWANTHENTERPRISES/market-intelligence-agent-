// Background service worker for Manifest V3

let socket = null;
let currentSymbol = "XAUUSD";
let currentTimeframe = "5M";
let currentPrice = null;
let backendBaseUrl = "http://127.0.0.1:8000";

function getWsUrl(baseUrl, symbol, price) {
  let raw = (baseUrl || "http://127.0.0.1:8000").trim().replace(/\/+$/, "");
  let wsBase = raw;
  if (wsBase.startsWith("http://")) {
    wsBase = wsBase.replace("http://", "ws://");
  } else if (wsBase.startsWith("https://")) {
    wsBase = wsBase.replace("https://", "wss://");
  } else if (!wsBase.startsWith("ws://") && !wsBase.startsWith("wss://")) {
    wsBase = "ws://" + wsBase;
  }
  return `${wsBase}/ws?symbol=${encodeURIComponent(symbol)}${price ? `&price=${price}` : ""}`;
}

// Restore stored active symbol & backendBaseUrl if available
if (typeof chrome !== "undefined" && chrome.storage && chrome.storage.local) {
  chrome.storage.local.get(["activeSymbol", "activeTimeframe", "backendBaseUrl"], (res) => {
    if (res.activeSymbol) currentSymbol = res.activeSymbol;
    if (res.activeTimeframe) currentTimeframe = res.activeTimeframe;
    if (res.backendBaseUrl) backendBaseUrl = res.backendBaseUrl;
  });

  if (chrome.storage.onChanged) {
    chrome.storage.onChanged.addListener((changes, area) => {
      if (area === "local" && changes.backendBaseUrl) {
        backendBaseUrl = changes.backendBaseUrl.newValue || "http://127.0.0.1:8000";
        if (socket) {
          try { socket.close(); } catch (e) {}
          socket = null;
        }
        connectWebSocket();
      }
    });
  }
}

function connectWebSocket() {
  if (socket && (socket.readyState === WebSocket.OPEN || socket.readyState === WebSocket.CONNECTING)) {
    return;
  }

  if (typeof chrome !== "undefined" && chrome.storage && chrome.storage.local) {
    chrome.storage.local.get(["backendBaseUrl"], (res) => {
      if (res.backendBaseUrl) backendBaseUrl = res.backendBaseUrl;
      _doConnect();
    });
  } else {
    _doConnect();
  }
}

function _doConnect() {
  try {
    const wsUrl = getWsUrl(backendBaseUrl, currentSymbol, currentPrice);
    socket = new WebSocket(wsUrl);

    socket.onopen = () => {
      console.log(`[Background] Connected to Market Intelligence WebSocket at ${wsUrl} for ${currentSymbol}`);
      subscribe(currentSymbol, currentTimeframe, currentPrice);
    };

    socket.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        if (typeof chrome !== "undefined" && chrome.tabs && chrome.tabs.query) {
          chrome.tabs.query({ url: ["*://*.tradingview.com/*", "*://tradingview.com/*"] }, (tabs) => {
            if (tabs && tabs.length > 0) {
              tabs.forEach((tab) => {
                if (tab && tab.id) {
                  chrome.tabs.sendMessage(tab.id, { type: "INTELLIGENCE_UPDATE", payload: data }).catch(() => {});
                }
              });
            }
          });
        }
      } catch (err) {
        console.error("[Background] Error parsing WS message:", err);
      }
    };

    socket.onclose = () => {
      setTimeout(connectWebSocket, 3000);
    };

    socket.onerror = () => {
      // Silence WebSocket errors
    };
  } catch (err) {
    setTimeout(connectWebSocket, 3000);
  }
}

function subscribe(symbol, timeframe, price) {
  if (!symbol) return;
  currentSymbol = symbol.toUpperCase();
  currentTimeframe = timeframe || "5M";
  if (price && price > 0) {
    currentPrice = price;
  }

  if (typeof chrome !== "undefined" && chrome.storage && chrome.storage.local) {
    chrome.storage.local.set({ activeSymbol: currentSymbol, activeTimeframe: currentTimeframe });
  }

  if (socket && socket.readyState === WebSocket.OPEN) {
    socket.send(JSON.stringify({
      action: "SUBSCRIBE",
      symbol: currentSymbol,
      timeframe: currentTimeframe,
      price: currentPrice
    }));
  }
}

if (typeof chrome !== "undefined" && chrome.runtime && chrome.runtime.onMessage) {
  chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
    if (message.type === "SYMBOL_CHANGED") {
      subscribe(message.symbol, message.timeframe || "5M", message.price);
      sendResponse({ status: "ok" });
    } else if (message.type === "REQUEST_REFRESH") {
      subscribe(currentSymbol, currentTimeframe, currentPrice);
      sendResponse({ status: "ok" });
    } else if (message.type === "SET_BACKEND_URL") {
      if (message.url) {
        backendBaseUrl = message.url;
        if (typeof chrome !== "undefined" && chrome.storage && chrome.storage.local) {
          chrome.storage.local.set({ backendBaseUrl: message.url });
        }
        if (socket) {
          try { socket.close(); } catch (e) {}
          socket = null;
        }
        connectWebSocket();
      }
      sendResponse({ status: "ok", backendBaseUrl });
    }
  });
}

connectWebSocket();
