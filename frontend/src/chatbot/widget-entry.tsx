/**
 * 外部サイト埋め込み用エントリポイント
 * <script src="https://your-domain.com/chatbot/widget.js"></script>
 * 1行で埋め込み可能。Shadow DOM でCSS隔離。
 */
import React from 'react';
import ReactDOM from 'react-dom/client';
import ChatWidget from './ChatWidget';

declare global {
  interface Window {
    __clinicChatbotApiBase?: string;
  }
}

const WIDGET_STYLES = `
/* ─── FAB ─── */
.cb-fab {
  position: fixed;
  bottom: 24px;
  right: 24px;
  width: 56px;
  height: 56px;
  border-radius: 50%;
  background: #3B82F6;
  color: white;
  font-size: 24px;
  border: none;
  cursor: pointer;
  box-shadow: 0 4px 12px rgba(0,0,0,0.3);
  z-index: 99999;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: transform 0.2s;
}
.cb-fab:hover { transform: scale(1.1); }

/* ─── Window ─── */
.cb-window {
  position: fixed;
  bottom: 24px;
  right: 24px;
  width: 370px;
  max-width: calc(100vw - 48px);
  height: 520px;
  max-height: calc(100vh - 48px);
  border-radius: 12px;
  background: #fff;
  box-shadow: 0 8px 30px rgba(0,0,0,0.25);
  z-index: 99999;
  display: flex;
  flex-direction: column;
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
  font-size: 14px;
  color: #1a1a1a;
  overflow: hidden;
}

/* ─── Header ─── */
.cb-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 16px;
  background: #3B82F6;
  color: white;
  flex-shrink: 0;
}
.cb-header-title { font-weight: 600; font-size: 15px; }
.cb-close-btn {
  background: none;
  border: none;
  color: white;
  font-size: 18px;
  cursor: pointer;
  padding: 4px 8px;
  border-radius: 4px;
}
.cb-close-btn:hover { background: rgba(255,255,255,0.2); }

/* ─── Messages ─── */
.cb-messages {
  flex: 1;
  overflow-y: auto;
  padding: 12px;
}

/* ─── Bubbles ─── */
.cb-bubble-row {
  display: flex;
  margin-bottom: 8px;
}
.cb-bubble-row--user { justify-content: flex-end; }
.cb-bubble-row--bot { justify-content: flex-start; }

.cb-bubble {
  max-width: 80%;
  padding: 10px 14px;
  border-radius: 12px;
  line-height: 1.5;
  word-break: break-word;
}
.cb-bubble--user {
  background: #3B82F6;
  color: white;
  border-bottom-right-radius: 4px;
}
.cb-bubble--bot {
  background: #f3f4f6;
  color: #1a1a1a;
  border-bottom-left-radius: 4px;
}

.cb-typing {
  color: #9ca3af;
  font-style: italic;
}

.cb-error {
  color: #ef4444;
  text-align: center;
  font-size: 13px;
  padding: 4px 0;
}

/* ─── Quick Replies ─── */
.cb-quick-replies {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  padding: 8px 12px;
  border-top: 1px solid #e5e7eb;
  flex-shrink: 0;
}
.cb-quick-btn {
  padding: 6px 14px;
  border: 1px solid #3B82F6;
  border-radius: 999px;
  background: white;
  color: #3B82F6;
  font-size: 13px;
  cursor: pointer;
  transition: all 0.15s;
}
.cb-quick-btn:hover {
  background: #3B82F6;
  color: white;
}
.cb-quick-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

/* ─── Input ─── */
.cb-input-area {
  display: flex;
  gap: 8px;
  padding: 10px 12px;
  border-top: 1px solid #e5e7eb;
  flex-shrink: 0;
}
.cb-input {
  flex: 1;
  padding: 8px 12px;
  border: 1px solid #d1d5db;
  border-radius: 8px;
  font-size: 14px;
  outline: none;
}
.cb-input:focus { border-color: #3B82F6; }
.cb-input:disabled { background: #f9fafb; }
.cb-send-btn {
  padding: 8px 14px;
  background: #3B82F6;
  color: white;
  border: none;
  border-radius: 8px;
  cursor: pointer;
  font-size: 14px;
}
.cb-send-btn:hover { background: #2563EB; }
.cb-send-btn:disabled { opacity: 0.5; cursor: not-allowed; }
`;

function mountWidget() {
  const current = document.currentScript as HTMLScriptElement | null;
  const attrApiBase = current?.getAttribute('data-api-base')?.trim();
  if (attrApiBase) {
    window.__clinicChatbotApiBase = attrApiBase.replace(/\/$/, '');
  } else if (current?.src) {
    const origin = new URL(current.src).origin;
    window.__clinicChatbotApiBase = `${origin}/api/web_chatbot`;
  }

  const host = document.createElement('div');
  host.id = 'clinic-chatbot-widget';
  document.body.appendChild(host);

  const shadow = host.attachShadow({ mode: 'open' });

  // Inject styles
  const style = document.createElement('style');
  style.textContent = WIDGET_STYLES;
  shadow.appendChild(style);

  // Mount React
  const mountPoint = document.createElement('div');
  shadow.appendChild(mountPoint);

  const root = ReactDOM.createRoot(mountPoint);
  root.render(React.createElement(ChatWidget));
}

// 自動マウント
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', mountWidget);
} else {
  mountWidget();
}
