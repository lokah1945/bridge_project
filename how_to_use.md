# 🌉 Bridge-Client: Usage Guide

This guide covers configuration, API usage, and the CLI for the rebuilt bridge-client.

## 🏗️ Architecture

- **Bridge-Server** (Windows): keeps a logged-in browser session alive and serves live cookies via `GET /get-session/{provider}`.
  - **Recommended**: `server/server.js` (Node.js) on port **9877** — full stealth with `playwright-extra` + `puppeteer-extra-plugin-stealth`.
  - **Alternative**: `bridge_server.py` (Python) on port **9877** (only run one server at a time).
- **Bridge-Client** (Linux): encrypts sessions, runs headless browser automation per request, and serves an OpenAI-compatible API on port **8000**.
- **Server only needs to be online during login and session refresh.** Once the client has cached the encrypted session, the server can be shut down until `SESSION_TTL_HOURS` expires.

## ⚙️ Configuration `.env`

Copy `.env.example` to `.env` and adjust:

```env
# Bridge-Server URL (default 9877 for both server.js and bridge_server.py; only run one at a time)
BRIDGE_SERVER_URL=http://host.zerotier.my.id:9877
PORT=8000
ENCRYPTION_KEY=<your-fernet-key>
SESSION_TTL_HOURS=24
MODEL_CACHE_TTL_MIN=60
API_KEY=optional-secret-key
CONCURRENCY_LIMIT=2
REQUEST_TIMEOUT=120
HEADLESS=true
DEBUG=false
```

## 🚀 Start the Gateway

```bash
pip install -r requirements.txt
python -m playwright install chromium
python client/client.py
```

The gateway will be available at `http://127.0.0.1:8000`.

## 🧠 Model Discovery

Models are discovered automatically and cached in `model.json` at the interval defined by `MODEL_CACHE_TTL_MIN` (default 60 minutes). You can trigger a manual refresh by restarting the gateway.

```bash
curl http://localhost:8000/v1/models
```

## 💬 Chat Completions

### Non-Streaming
```bash
curl http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $API_KEY" \
  -d '{
    "model": "bridge/qwen/qwen-max",
    "messages": [{"role": "user", "content": "Hello"}],
    "extra_params": {"thinking": "fast", "tools": true}
  }'
```

### Streaming
```bash
curl http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $API_KEY" \
  -d '{
    "model": "bridge/arena/text/gpt-4o",
    "messages": [{"role": "user", "content": "Hello"}],
    "stream": true
  }'
```

### OpenAI Python SDK
```python
from openai import OpenAI

client = OpenAI(
    base_url="http://127.0.0.1:8000/v1",
    api_key="your-api-key-or-anything",
)

response = client.chat.completions.create(
    model="bridge/deepseek/deepseek-v3",
    messages=[{"role": "user", "content": "Hello"}],
    stream=True,
)
for chunk in response:
    print(chunk.choices[0].delta.content or "", end="")
```

## 🖥️ CLI

```bash
# Install CLI
pip install -e .

# Check health
bridge-cli health

# List available models
bridge-cli models

# One-shot
bridge-cli chat -m bridge/qwen/qwen-max "Hello"

# Interactive REPL
bridge-cli chat -m bridge/deepseek/deepseek-v3 -i

# With system prompt and extra params
bridge-cli chat -m bridge/arena/text/gpt-4o \
  --system "You are a coding assistant" \
  --param temporary_chat=true \
  "Write a Python function to sort a list"

# Point CLI at a remote gateway
export BRIDGE_API_BASE_URL=http://remote:8000
bridge-cli chat -m bridge/qwen/qwen-max "Hi"

# Session status
bridge-cli session status
```

## 🛡️ Feature Matrix (`extra_params`)

| Provider | Param | Values | Effect |
| :--- | :--- | :--- | :--- |
| **Arena** | `temporary_chat` | `true`/`false` | Use a temporary session with no history. |
| **Arena** | `aspect_ratio` | `"1:1"`, `"16:9"`, etc. | Image generation aspect ratio. |
| **Qwen** | `thinking` | `auto`/`thinking`/`fast` | Reasoning mode. |
| **Qwen** | `tools` | `true`/`false` | Enable/disable web search / tools. |
| **DeepSeek** | `mode` | `fast`/`expert` | Latency vs deep reasoning. |
| **DeepSeek** | `thinking` | `true`/`false` | Enable thought process. |
| **DeepSeek** | `search` | `true`/`false` | Enable web search. |

## ✅ Acceptance Checklist

- `pip install -r requirements.txt` succeeds.
- `python client/client.py` starts without errors.
- `GET /v1/models` returns cached models.
- `POST /v1/chat/completions` returns valid OpenAI schema for each provider.
- Streaming output is valid SSE.
- CLI one-shot and REPL work end-to-end.
- No cookies/encryption keys are logged.
