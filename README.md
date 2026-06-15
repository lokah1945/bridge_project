# 🌉 Bridge-Project: OpenAI-Compatible AI Gateway

Bridge-Project converts Web UI chat providers (Arena.ai, Qwen.ai, DeepSeek) into an OpenAI-compatible API that can be used from any CLI, SDK, or HTTP client.

## 🏗️ Architecture: Hub-and-Spoke Automation

The system is split into two components to maximize stealth and bypass bot detection.

### 1. Bridge-Server (The Session Hub)
- **Role**: Session provider.
- **Platform**: Windows Server (headfull browser) or any machine that can run a logged-in browser.
- **Function**: Keeps browser sessions alive, performs manual login, and exposes `GET /get-session/{provider}` with live cookies + headers + user-agent.
- **Implementations**:
  - `bridge_server.py` (Python / FastAPI) on port **99876**.
  - `server/server.js` (Node.js / Express) on port **9877** (legacy alternative).
- **Stealth**: Uses CDP (Chrome DevTools Protocol) and `playwright-stealth` to override `navigator.webdriver` and browser fingerprints.

### 2. Bridge-Client (The Automation Engine)
- **Role**: Execution gateway.
- **Platform**: Linux / Server.
- **Function**:
    - Fetches and encrypts sessions (AES-256 via Fernet).
    - Runs headless browser automation to operate the provider Web UI directly.
    - Exposes an OpenAI-compatible API on `PORT` (default **8000**).
    - Provides a CLI for one-shot and interactive chat.

## 🚀 Key Features

- **1:1 Functional Parity**: Operates the Web UI directly, enabling provider-specific features.
- **Dynamic Model Discovery**: Automatically discovers models and stores them in `model.json`, refreshed every 60 minutes.
- **Stateless Execution**: Uses temporary chat endpoints and clears cookies after every request.
- **OpenAI Compatible**: Works with `curl`, Python `requests`, `openai` SDK, and any OpenAI-compatible client.
- **CLI Client**: `python -m client.cli chat -m bridge/qwen/qwen-max "Hello"`.

## 🛠️ Deployment Guide

### Bridge-Server (Python — currently active)
1. Install Python 3.10+.
2. `pip install -r requirements.txt`
3. `python bridge_server.py`
4. Open the browser window, navigate to each provider, and log in manually.
5. The client will call `GET /get-session/{provider}` to fetch live cookies.

### Bridge-Client (Linux)
1. Install Python 3.10+.
2. `pip install -r requirements.txt`
3. `python -m playwright install chromium`
4. Copy `.env.example` to `.env` and set `BRIDGE_SERVER_URL`.
5. `python client/client.py`

## 🗺️ Provider Capabilities

| Provider | Format | Modality / Feature |
| :--- | :--- | :--- |
| **Arena.ai** | `bridge/arena/<modality>/<model>` | `text`, `search`, `image`, `code` |
| **Qwen.ai** | `bridge/qwen/<model>` | `thinking`, `tools` |
| **DeepSeek** | `bridge/deepseek/<model>` | `mode`, `thinking`, `search` |

## 🔒 Security
- **Session Encryption**: Cookies are encrypted with Fernet (AES-256) before local storage.
- **Optional API Key**: Set `API_KEY` in `.env` to require `Authorization: Bearer <token>` on all `/v1/*` endpoints.
- **Zero Footprint**: Each request uses a fresh browser context and clears cookies afterward.

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
