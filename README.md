# 🌉 Bridge-Project: Enterprise AI Gateway

Bridge-Project is a high-performance, stealthy automation gateway that converts various AI providers (Arena.ai, Qwen, DeepSeek) into a single, OpenAI-compatible API.

## 🏗️ Architecture: Hub-and-Spoke Automation

The system is split into two components to maximize stealth and bypass bot detection (Cloudflare, Google, etc.).

### 1. Bridge-Server (The Session Hub)
- **Role**: Session Provider.
- **Platform**: Windows Server (Headfull Browser).
- **Function**: Maintains active browser sessions, handles manual login, and provides cookies/headers via `/get-session`.
- **Stealth**: Uses CDP (Chrome DevTools Protocol) to override `navigator.webdriver` and browser fingerprints at the engine level.

### 2. Bridge-Client (The Automation Engine)
- **Role**: Execution Gateway.
- **Platform**: Linux / Server.
- **Function**: 
    - Fetches and encrypts sessions (AES-256).
    - Orchestrates headless browser automation to interact with Provider Web UIs.
    - Exposes an OpenAI-compatible API (`/v1/chat/completions`).
- **Stealth**: Integrates `playwright-extra`, `stealth`, and `CDP` overrides.

## 🚀 Key Features

- **1:1 Functional Parity**: Operates the Web UI directly, enabling features that are often unavailable in basic APIs.
- **Dynamic Model Discovery**: Automatically scrapes all available models from providers, including "Expanded" lists in Qwen and multi-modality in Arena.
- **Stateless Execution**: Uses temporary chat endpoints and clears cookies after every request to ensure zero history on the account.
- **Model Caching**: Stores discovered models in `model.json` and updates every 60 minutes.
- **OpenAI Compatible**: Easily integrable with Cursor, LibreChat, or any OpenAI-compatible client.

## 🛠️ Deployment Guide

### Bridge-Server (Windows)
1. Install Node.js.
2. `cd server && npm install`
3. `node server.js`
4. Use the CLI to create a profile $\rightarrow$ Start Server $\rightarrow$ Login via the provided URL.

### Bridge-Client (Linux)
1. Install Python 3.10+.
2. `pip install -r requirements.txt`
3. Setup `.env` using `.env.example`.
4. `python client/client.py`

## 🗺️ Provider Capabilities

| Provider | Feature | Implementation |
| :--- | :--- | :--- |
| **Arena.ai** | Multi-Modality | Supports `/text`, `/search`, `/image`, `/code` direct endpoints. |
| **Qwen.ai** | Expanded Models | Automatically clicks "Expand More" to access all models. |
| **DeepSeek** | Expert Mode | Toggles Expert/Reasoning/Search modes via DOM. |

## 🔒 Security
- **Session Encryption**: Cookies are never stored in plain text; they are encrypted using Fernet (AES-256).
- **Zero Footprint**: Navigates to temporary/anonymous endpoints to avoid account history logging.
