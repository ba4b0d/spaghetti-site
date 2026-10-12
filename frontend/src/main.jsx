import React from 'react';
import ReactDOM from 'react-dom/client';
import { BrowserRouter } from 'react-router-dom';
import App from './App';
import { applyDynamicBranding } from './lib/branding';
import './fonts.css';
import './index.css';

// Apply favicon/logo from backend settings (if set) — public endpoint, no auth required
applyDynamicBranding();

// Drop stale dual-theme preference (app is single soft-dusk only)
try {
  localStorage.removeItem('spaghetti-theme');
  localStorage.removeItem('3djat-theme');
} catch {
  /* ignore */
}

// Register service worker for PWA offline support
if ('serviceWorker' in navigator) {
  window.addEventListener('load', () => {
    navigator.serviceWorker.register('/sw.js?v=5').catch(() => {});
  });
}

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <BrowserRouter>
      <App />
    </BrowserRouter>
  </React.StrictMode>
);
