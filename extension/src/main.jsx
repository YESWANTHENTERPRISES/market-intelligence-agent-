import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App.jsx";

const rootEl = document.getElementById("root");
if (rootEl) {
  ReactDOM.createRoot(rootEl).render(
    <React.StrictMode>
      <App />
    </React.StrictMode>
  );
}

// Global injection mount helper for extension content script
window.mountIntelligenceTerminal = (containerEl) => {
  if (!containerEl) return;
  ReactDOM.createRoot(containerEl).render(
    <React.StrictMode>
      <App />
    </React.StrictMode>
  );
};
