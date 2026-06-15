# 🖥️ Bridge-Server (Node.js) — Recommended Windows Session Hub

This folder contains the **recommended** Bridge-Server implementation for Windows. It uses `playwright-extra` + `puppeteer-extra-plugin-stealth` + CDP to keep a logged-in browser session alive and serve live cookies via `GET /get-session/{provider}`.

## Why Node.js on Windows?

- Supports `puppeteer-extra-plugin-stealth` (Node-only).
- Persistent browser profiles (`browser_sessions/`).
- Headfull browser for manual login.
- The server only needs to be active during login and when the client refreshes sessions.

## 🛠️ Requirements
- Node.js 18+
- Windows Server or Windows desktop (with ZeroTier if accessing remotely)

## 🚀 Installation

```bash
cd server
npm install
npx playwright install chromium
```

## ⚡ Activation

```bash
node server.js
```

Then in the terminal menu:
1. Add a profile (e.g., `Google83`).
2. Start the server.
3. A browser window opens. Log in to Arena, Qwen, and DeepSeek manually.
4. The client will fetch cookies from `http://<windows-ip>:9877/get-session/{provider}`.

## 🔑 Login URLs

The server also exposes an `/open` endpoint to navigate the browser to a provider:

```
http://localhost:9877/open?url=https://arena.ai/text/direct
http://localhost:9877/open?url=https://chat.qwen.ai/
http://localhost:9877/open?url=https://chat.deepseek.com/
```

## 📡 API Endpoints

- `GET /health` — server and browser status.
- `GET /get-session/:provider` — live cookies + user-agent + headers for `arena`, `qwen`, `deepseek`.
- `GET /open?url=...` — open a URL in the server browser.

## 📝 Python Alternative

If you prefer a Python-only environment, use `bridge_server.py` in the repo root (port **9877** by default). It uses `playwright` + `playwright-stealth` + CDP.
