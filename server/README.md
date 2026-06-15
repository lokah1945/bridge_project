# 🖥️ Bridge-Server (Node.js) - Installation Guide

This folder contains the original Node.js implementation of the Bridge-Server. It is an alternative to the Python-based `bridge_server.py` in the repo root.

## 🛠️ Requirements
- Node.js 18+
- Windows Server (or any machine that can run a headfull browser)

## 🚀 Installation

1. **Extract the folder.**
2. **Install Dependencies:**
   ```bash
   npm install
   ```
3. **Install Browser:**
   ```bash
   npx playwright install chromium
   ```
4. **Configure:**
   Edit `.env` to set the `PORT` (Default: 9877).

## ⚡ Activation
Run the server:
```bash
npm start
```

## 🔑 How it Works
1. The server opens a browser.
2. You can manually log in to providers (Arena, Qwen, DeepSeek) via the browser window.
3. The **Bridge-Client** will call `GET /get-session/<provider>` to fetch the latest cookies.

## 📝 Note
The rebuilt client also supports the Python server in the repo root (`bridge_server.py` on port 99876). Use whichever matches your environment.
