# 🌉 Bridge-Project: OpenAI-Compatible AI Gateway

Bridge-Project converts Web UI chat providers (Arena.ai, Qwen.ai, DeepSeek) into an OpenAI-compatible API that can be used from any CLI, SDK, or HTTP client.

## 🏗️ Architecture: Hub-and-Spoke Automation

The system is split into two components to maximize stealth and bypass bot detection.

### 1. Bridge-Server (Windows — Session Hub)
- **Role**: Session provider.
- **Platform**: Windows (headfull browser for manual login).
- **Function**: Keeps browser sessions alive, performs manual login, and exposes `GET /get-session/{provider}` with live cookies + headers + user-agent.
- **Recommended implementation**: `server/server.js` (Node.js) — uses `playwright-extra` + `puppeteer-extra-plugin-stealth` + CDP for full stealth.
- **Alternative**: `bridge_server.py` (Python/FastAPI) — uses `playwright` + `playwright-stealth` + CDP. Port **9877** by default (same as server.js, only run one at a time).
- **Server only needs to be active during login and when the client refreshes sessions**. Once the client has cached an encrypted session, the server can be shut down until the session expires.

### 2. Bridge-Client (Linux — Runtime Engine)
- **Role**: Execution gateway and CLI.
- **Platform**: Linux / Server (headless browser).
- **Function**:
    - Fetches and encrypts sessions (AES-256 via Fernet).
    - Runs headless browser automation to operate the provider Web UI directly.
    - Exposes an OpenAI-compatible API on `PORT` (default **8000**).
    - Provides a CLI for one-shot and interactive chat.
- **Design**: Browser is launched only when processing a request and is closed immediately after. Minimal active browser usage.

## 🚀 Key Features

- **1:1 Functional Parity**: Operates the Web UI directly, enabling provider-specific features.
- **Dynamic Model Discovery**: Automatically discovers models and stores them in `model.json`, refreshed every 60 minutes.
- **Stateless Execution**: Uses temporary chat endpoints and clears cookies/localStorage after every request.
- **OpenAI Compatible**: Works with `curl`, Python `requests`, `openai` SDK, and any OpenAI-compatible client.
- **CLI First**: `python -m client.cli chat -m bridge/qwen/qwen-max "Hello"`.

## 🛠️ Deployment Guide

### Bridge-Server (Windows — recommended: `server/server.js`)
1. Install Node.js 18+.
2. `cd server && npm install`
3. `npx playwright install chromium`
4. `node server.js`
5. Create a profile, start the server, then log in manually to each provider in the browser window.
6. The client will call `GET /get-session/{provider}` on port **9877**.

### Bridge-Server (Windows — alternative: `bridge_server.py`)
1. `pip install -r requirements.txt`
2. `python -m playwright install chromium`
3. `python bridge_server.py` (port **9877**)
4. Log in manually via the opened browser window.
5. Set `BRIDGE_SERVER_URL=...:9877` in the client `.env`.

### Bridge-Client (Linux)
1. Install Python 3.10+.
2. `pip install -r requirements.txt`
3. `python -m playwright install chromium`
4. Copy `.env.example` to `.env` and set `BRIDGE_SERVER_URL` (default **9877** for `server/server.js`).
5. `python client/client.py` or `python -m client.client`

## 🗺️ Provider Capabilities

| Provider | Format | Modality / Feature |
| :--- | :--- | :--- |
| **Arena.ai** | `bridge/arena/<modality>/<model>` | `text`, `search`, `image`, `code` |
| **Qwen.ai** | `bridge/qwen/<model>` | `thinking`, `tools` |
| **DeepSeek** | `bridge/deepseek/<model>` | `mode`, `thinking`, `search` |

## 🔒 Security
- **Session Encryption**: Cookies are encrypted with Fernet (AES-256) before local storage.
- **Optional API Key**: Set `API_KEY` in `.env` to require `Authorization: Bearer <token>` on all `/v1/*` endpoints.
- **Zero Footprint**: Each request uses a fresh browser context and clears cookies/localStorage afterward.

## 🧪 CLI Examples

```bash
# List models
python -m client.cli models

# One-shot chat
python -m client.cli chat -m bridge/qwen/qwen-max "What is the capital of France?"

# Interactive REPL
python -m client.cli chat -m bridge/deepseek/deepseek-v3 -i

# With extra provider params
python -m client.cli chat -m bridge/arena/text/gpt-4o \
  --param temporary_chat=true \
  "Explain quantum computing"
```

## 📚 More Docs
- `how_to_use.md` — detailed configuration and API examples.
- `model.md` — full model matrix and `extra_params` reference.
- `AUDIT_REPORT.md` — audit findings and rebuild plan.
