// Background service worker for Manifest V3

let socket = null;
let currentSymbol = "XAUUSD";
let currentTimeframe = "5M";
let currentPrice = null;

// Restore stored active symbol if available
if (typeof chrome !== "undefined" && chrome.storage && chrome.storage.local) {
  chrome.storage.local.get(["activeSymbol", "activeTimeframe"], (res) => {
    if (res.activeSymbol) currentSymbol = res.activeSymbol;
    if (res.activeTimeframe) currentTimeframe = res.activeTimeframe;
  });
}

function connectWebSocket() {
  if (socket && (socket.readyState === WebSocket.OPEN || socket.readyState === WebSocket.CONNECTING)) {
    return;
  }

  try {
    const wsUrl = `ws://127.0.0.1:8000/ws?symbol=${encodeURIComponent(currentSymbol)}${currentPrice ? `&price=${currentPrice}` : ""}`;
    socket = new WebSocket(wsUrl);

    socket.onopen = () => {
      console.log(`[Background] Connected to Market Intelligence WebSocket for ${currentSymbol}`);
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
    }
  });
}

connectWebSocket();
