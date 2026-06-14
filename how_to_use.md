# bridge-client — usage

## Architecture

```
                       (already running, headfull Chrome with manual login)
                       ┌────────────────────────────────────────────────┐
                       │          bridge-server  (Windows)               │
                       │  Express + Playwright + persistent Chrome       │
                       │                                                │
                       │  /health              →  {status: online}      │
                       │  /get-session/arena   →  {cookies, ua, headers}│
                       │  /get-session/qwen    →  {cookies, ua, headers}│
                       │  /get-session/deepseek → 404 if not logged in  │
                       └────────────────────┬───────────────────────────┘
                                            │  HTTP (cookies sync)
                                            ▼
       ┌────────────────────────────────────────────────────────────────┐
       │                    bridge-client  (Linux)  ← YOU ARE HERE       │
       │  FastAPI + Playwright (headless) + Fernet (AES-256)            │
       │                                                                │
       │  sessions/   ← encrypted *.bin (one per provider, Fernet)      │
       │  model.json  ← dynamic model cache (refreshed every 60 min)    │
       │                                                                │
       │  /health                →  status                              │
       │  /v1/models             →  294+ model ids                      │
       │  /v1/chat/completions   →  OpenAI-compatible chat              │
       └────────────────────────────────────────────────────────────────┘
                                            │
                                            ▼
       ┌────────────────────────────────────────────────────────────────┐
       │          AI provider Web UIs (driven by headless Chromium)     │
       │  arena.ai/{text,search,image,code}/direct                      │
       │  chat.qwen.ai/?temporary-chat=true                             │
       │  chat.deepseek.com/                                            │
       └────────────────────────────────────────────────────────────────┘
```

Lifecycle:
1. **Manual login once** — done in bridge-server's headfull Chrome.
2. **Client sync** — pulls cookies + UA, encrypts locally (Fernet).
3. **Client operates** — runs Playwright headless directly.  The
   server can be turned off.
4. **Auto re-sync** — if a provider rejects the session (401/403 /
   redirect to login), the client transparently re-syncs.

## Setup

```bash
git clone <repo>
cd bridge-client
pip install -r requirements.txt
playwright install chromium
playwright install-deps          # fixes libnspr4.so on Debian/Ubuntu
cp .env.example .env
# (optional) edit .env to change BRIDGE_SERVER_URL / PORT / etc.
```

`.env` keys (see `.env.example` for defaults):

```
BRIDGE_SERVER_URL=http://host.zerotier.my.id:9877
PORT=8000
ENCRYPTION_KEY=                # auto-generated on first start
SESSION_TTL_HOURS=24           # refresh from bridge-server after this
MODEL_CACHE_REFRESH_MINUTES=60 # background refresh interval
BROWSER_HEADLESS=true
```

## Running

```bash
python3 client.py
```

Server log shows:
- arena(text): 137 raw options → 135 after filter
- arena(search): 17 → 16
- arena(image): 49 → 47
- arena(code): 74 → 73
- qwen primary models: 3
- qwen expanded models: 23 (added 20)
- deepseek: NO_SESSION (or, once logged in: N models)

## API examples

### Health check

```bash
curl http://localhost:8000/health
# {"status":"ok","model_cache_updated_at":"...","providers":{"arena":"ok","qwen":"ok","deepseek":"NO_SESSION"}}
```

### List models

```bash
curl http://localhost:8000/v1/models | jq '.data | length'
# 294
curl http://localhost:8000/v1/models | jq '.data[].id' | head
```

### Chat (non-streaming)

```bash
curl -X POST http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "bridge/qwen/Qwen3.5-Flash",
    "messages": [{"role":"user","content":"hallo"}]
  }'
```

### Chat (streaming)

```bash
curl -N -X POST http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "bridge/qwen/Qwen3.5-Flash",
    "messages": [{"role":"user","content":"hallo"}],
    "stream": true
  }'
```

### Per-provider examples

**Arena (text)**

```bash
curl -X POST http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "bridge/arena/text/gemini-3-flash",
    "messages": [{"role":"user","content":"hallo"}],
    "extra_params": {"temporary_chat": true}
  }'
```

**Qwen — with thinking mode**

```bash
curl -X POST http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "bridge/qwen/Qwen3.7-Max",
    "messages": [{"role":"user","content":"hallo"}],
    "extra_params": {"thinking": "auto", "tools": true}
  }'
```

**DeepSeek — with expert mode**

```bash
curl -X POST http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "bridge/deepseek/deepseek-chat",
    "messages": [{"role":"user","content":"hallo"}],
    "extra_params": {"mode": "expert", "thinking": false, "search": false}
  }'
```

## Feature matrix (extra_params)

| Provider | Parameter      | Values                  | Effect                                          |
|----------|----------------|-------------------------|--------------------------------------------------|
| arena    | modality       | text/search/image/code  | Set from model path; do not pass explicitly     |
| arena    | temporary_chat | true (default)          | Zero-footprint (already via /direct endpoint)   |
| qwen     | thinking       | auto/thinking/fast      | Controls Chain-of-Thought reasoning depth        |
| qwen     | tools          | true/false              | Toggle web-search & plugin tools                 |
| deepseek | mode           | fast/expert             | Latency vs deep reasoning                        |
| deepseek | thinking       | true/false              | Toggle thought-process (CoT)                    |
| deepseek | search         | true/false              | Toggle web search                                |

## Statelessness / zero footprint

| Provider | How                                           |
|----------|-----------------------------------------------|
| arena    | navigate to /direct (already ephemeral) + clear_cookies() after every execute() |
| qwen     | ALWAYS use `?temporary-chat=true` (no history saved) + clear_cookies()             |
| deepseek | clear_cookies() after every execute()                                            |

Each provider instance is used **once per request** then cleaned up via
`BaseProvider.cleanup()` — no browser process leaks, no account history
pollution.

## Re-sync flow

1. `client.py::get_effective_session(provider)` checks the local encrypted
   session (`sessions/<provider>.bin`).
2. If missing OR expired, it calls
   `GET BRIDGE_SERVER_URL/get-session/<provider>` with 20 s timeout.
3. On success → `SessionManager.save_session()` writes the new Fernet
   ciphertext.
4. On failure BUT local session exists → graceful degradation: use
   stale session, log a WARNING.
5. On failure AND no local session → HTTP 503 `AUTH_REQUIRED`.

The background loop (`model_cache_loop`) refreshes `model.json` every
`MODEL_CACHE_REFRESH_MINUTES` minutes (default 60).

## Adding a new provider

1. Create `providers/<name>.py` with a `BaseProvider` subclass
   implementing `list_models(**kwargs)` and `execute(model_id, prompt,
   params)`.
2. Decorate the class with `@ProviderRegistry.register("<name>")`.
3. Restart the gateway.

No changes to `client.py` or `registry.py` are needed — the next
import will auto-register the new provider.
