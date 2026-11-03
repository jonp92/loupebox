import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import App from "./App";
import { AuthProvider } from "./auth";
import { ConfirmProvider } from "./confirm";
import { ToastProvider } from "./toast";
import "./styles.css";

// Installable PWA + offline shell. Production only, so dev servers never serve stale assets.
if (import.meta.env.PROD && "serviceWorker" in navigator) {
  window.addEventListener("load", () => {
    navigator.serviceWorker.register("/sw.js").catch(() => {});
  });
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <BrowserRouter>
      <AuthProvider>
        <ToastProvider><ConfirmProvider><App /></ConfirmProvider></ToastProvider>
      </AuthProvider>
    </BrowserRouter>
  </StrictMode>,
);
