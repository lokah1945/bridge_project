# 🖥️ Bridge-Server (Node.js) - Installation Guide

This server acts as the **Credential Hub**. It runs a browser instance on your Windows Server to maintain active sessions.

## 🛠️ Requirements
- Node.js 18+
- Windows Server (with ZeroTier installed)

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
2. You can manually log in to providers (Arena, etc.) via the browser window.
3. The **Bridge-Client** will call `GET /get-session/<provider>` to fetch the latest cookies.
