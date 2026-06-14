# bridge-client — usage

## Architecture

```
                       (already running, headfull Chrome with manual login)
                       ┌────────────────────────────────────────────────┐
                       │          bridge-server  (Windows)               │
                       │  Express + persistent headfull Chrome       │
                       │                                                │
                       │  /health              →  {status: online}      │
                       │  /get-session/arena   →  {cookies, ua, headers}│
                       │  /get-session/qwen    →  {cookies, ua, headers}│
                       │  /open?url=<URL>      →  opens URL in headfull │
                       │     (for manual re-login when cookies expire) │
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
       │  GET  /health                                                │
       │  GET  /v1/models                                             │
       │  POST /v1/chat/completions                                    │
       │  POST /admin/login/<provider>     ← trigger bridge-server     │
       │  POST /admin/refresh/<provider>    ← pull fresh cookies      │
       │  POST /admin/refresh-cache         ← re-discover all models  │
       └────────────────────────────────────────────────────────────────┘
                                            │
                                            ▼
       ┌────────────────────────────────────────────────────────────────┐
       │          AI provider Web UIs (driven by headless Chromium)     │
       │  arena.ai/{text,search,image,code}/direct                      │
       │  chat.qwen.ai/?temporary-chat=true                             │
       │  chat.deepseek.com/                                            │
       │  www.kimi.com/                                                │
       └────────────────────────────────────────────────────────────────┘
```

The lifecycle:
1. **Manual login once** — done in bridge-server's headfull Chrome.
2. **Client sync** — pulls cookies + UA, encrypts locally (Fernet).
3. **Client operates** — runs Playwright headless directly.  The
   server can be turned off.
4. **Auto re-sync** — if a provider rejects the session, the client
   transparently re-syncs.

## Setup

```bash
git clone https://github.com/lokah1945/bridge_project.git
cd bridge_project/bridge-client
pip install -r requirements.txt
playwright install chromium
playwright install-deps          # fixes libnspr4.so on Debian/Ubuntu
cp .env.example .env
python3 client.py                # starts the gateway on :8000
```

`.env` keys (see `.env.example` for defaults):

```
BRIDGE_SERVER_URL=http://host.zerotier.my.id:9877
PORT=8000
ENCRYPTION_KEY=                # auto-generated on first start
SESSION_TTL_HOURS=24           # refresh session from bridge-server after this
MODEL_CACHE_REFRESH_MINUTES=60 # background refresh interval for model.json
BROWSER_HEADLESS=true
```

## How providers share cookies (fallback chain)

bridge-server only exposes two profiles via `/get-session/<provider>`:
`arena` and `qwen`.  However, the Chromium user-data-dir behind those
profiles also contains cookies for `chat.deepseek.com` and `www.kimi.com`
because the user logged into those services at some point.

When `/get-session/deepseek` returns 404, the client falls back to
`arena`'s cookie blob (which contains the chat.deepseek.com cookies):

```python
PROVIDER_FALLBACKS = {
    "kimi":     ["arena", "qwen"],
    "deepseek": ["arena", "qwen"],
}
```

## Manual re-login flow (when cookies expire)

Eventually the cookies in the Chromium profile expire (e.g. Google OAuth
refresh tokens, login session JWTs).  When that happens, chat requests
will return a clean error message — but you can trigger a fresh login
via the admin endpoints.

**Three-step helper**: from the bridge-client directory,

```bash
python3 login_helper.py deepseek
```

This will:
1. POST `/admin/login/deepseek` — triggers bridge-server's
   `/open?url=https://chat.deepseek.com/` which navigates the
   persistent headfull Chrome to chat.deepseek.com.
2. **You** log in there manually (Google/email/Apple).
3. POST `/admin/refresh/deepseek` — pulls the fresh cookie blob from
   `/get-session/arena` (fallback), encrypts it locally, re-runs model
   discovery.

Same flow for `kimi`:

```bash
python3 login_helper.py kimi
# or, if you've already logged in via bridge-server:
python3 login_helper.py --refresh-only kimi
```

### Equivalent curl sequence

```bash
# 1. Trigger login in bridge-server's headfull Chrome
curl -X POST http://localhost:8000/admin/login/deepseek

# (you log in manually in bridge-server's Chrome window)

# 2. Pull fresh cookies + refresh cache
curl -X POST http://localhost:8000/admin/refresh/deepseek

# 3. Verify
curl http://localhost:8000/v1/models | jq '.data[] | select(.id | startswith("bridge/deepseek/"))'
```

## API

### `GET /health`

Liveness probe + cache status.

```bash
curl http://localhost:8000/health
```

### `GET /v1/models`

OpenAI-compatible model list.  Instant — served from `model.json`
in-process (no browser launched).

```bash
curl http://localhost:8000/v1/models | jq '.data | length'
# 301
```

Model name format:

```
bridge/arena/<modality>/<model_id>     modality ∈ {text, search, image, code}
bridge/qwen/<model_id>
bridge/deepseek/<model_id>
bridge/kimi/<model_id>
```

### `POST /v1/chat/completions`

```bash
# non-streaming
curl -X POST http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "bridge/qwen/Qwen3-Coder",
    "messages": [{"role":"user","content":"hallo"}]
  }'

# streaming (Server-Sent Events, OpenAI format)
curl -N -X POST http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "bridge/qwen/Qwen3-Coder",
    "messages": [{"role":"user","content":"hallo"}],
    "stream": true
  }'
```

#### Feature matrix (`extra_params`)

| Provider | Parameter      | Values                  | Effect                                          |
|----------|----------------|-------------------------|--------------------------------------------------|
| arena    | modality       | text/search/image/code  | Set from the model path; do not pass explicitly |
| arena    | temporary_chat | true (default)          | Zero-footprint (already via `/direct`)           |
| qwen     | thinking       | auto/thinking/fast      | Controls Chain-of-Thought reasoning depth        |
| qwen     | tools          | true/false              | Toggle web-search & plugin tools                 |
| deepseek | mode           | fast/expert             | Latency vs deep reasoning                        |
| deepseek | thinking       | true/false              | Toggle thought-process (CoT)                    |
| deepseek | search         | true/false              | Toggle web search                                |
| kimi     | (none for now) | -                       | Model selector popup only                        |

### `POST /admin/login/{provider}`

Opens the provider's login URL in bridge-server's persistent
headfull Chrome.  Returns instructions for the user.

```bash
curl -X POST http://localhost:8000/admin/login/kimi
# {"status":"login_triggered","provider":"kimi","url":"https://www.kimi.com/",
#  "bridge_server_response":"Navigated to https://www.kimi.com/",
#  "next_steps":["1. bridge-server has opened ...", ...]}
```

### `POST /admin/refresh/{provider}`

Force-pull fresh cookies from bridge-server (using fallback chain for
kimi/deepseek), encrypt locally, and re-discover models.  Call this
**after** the user has logged in via `/admin/login`.

```bash
curl -X POST http://localhost:8000/admin/refresh/deepseek
# {"status":"refreshed","provider":"deepseek","cookie_count":120,...}
```

### `POST /admin/refresh-cache`

Force-refresh the entire model cache from all providers.

```bash
curl -X POST http://localhost:8000/admin/refresh-cache
```

## Statelessness / zero footprint

| Provider | How                                           |
|----------|-----------------------------------------------|
| arena    | navigate to /direct (already ephemeral) + clear_cookies() after every execute() |
| qwen     | ALWAYS use `?temporary-chat=true` (no history saved) + clear_cookies() after every execute() |
| deepseek | clear_cookies() after every execute()         |
| kimi     | clear_cookies() after every execute()         |

Each provider instance is used **once per request** then cleaned up via
`BaseProvider.cleanup()` — no browser process leaks, no account history
pollution.

## How the session cache works

```
client.py::get_effective_session(provider):
  1. local = load sessions/<provider>.bin (Fernet-decrypted)
  2. if local exists AND not expired (default TTL 24 h):
        return local
  3. else:
        fresh = GET BRIDGE_SERVER_URL/get-session/<provider> (20 s timeout)
        if fresh:
            save to sessions/<provider>.bin
            return fresh
        for fallback in ["arena", "qwen"]:   # kimi/deepseek only
            fb = GET /get-session/<fallback>
            if fb has cookies:
                save under both names
                return fb
        if local exists (stale):
            return local (graceful degradation, WARNING)
        AUTH_REQUIRED → HTTP 503
```

## Adding a new provider

1. Create `providers/<name>.py` with a `BaseProvider` subclass
   implementing `list_models(**kwargs)` and
   `execute(model_id, prompt, params)`.
2. Decorate the class with `@ProviderRegistry.register("<name>")`.
3. Add the provider name to the `for provider_name in (...)` tuple in
   `client.py::update_model_cache` so discovery runs.
4. (Optional) Add a URL to `LOGIN_URLS` for the `/admin/login/<name>`
   endpoint.
5. Restart the gateway.
