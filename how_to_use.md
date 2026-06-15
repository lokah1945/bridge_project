# 🌉 Bridge-Client: Usage Guide

This guide covers configuration, API usage, and the CLI for the rebuilt bridge-client.

## 🏗️ Architecture

- **Bridge-Server** (`bridge_server.py` on port 99876): keeps a logged-in browser session alive and serves live cookies via `GET /get-session/{provider}`.
- **Bridge-Client** (`client/client.py` on port 8000): encrypts sessions, runs headless browser automation, and serves an OpenAI-compatible API.

## ⚙️ Configuration `.env`

Copy `.env.example` to `.env` and adjust:

```env
BRIDGE_SERVER_URL=http://host.zerotier.my.id:99876
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
# List available models
python -m client.cli models

# One-shot
python -m client.cli chat -m bridge/qwen/qwen-max "Hello"

# Interactive REPL
python -m client.cli chat -m bridge/deepseek/deepseek-v3 -i

# With system prompt and extra params
python -m client.cli chat -m bridge/arena/text/gpt-4o \
  --system "You are a coding assistant" \
  --param temporary_chat=true \
  "Write a Python function to sort a list"

# Point CLI at a remote gateway
python -m client.cli --base-url http://remote:8000 chat -m bridge/qwen/qwen-max "Hi"
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
