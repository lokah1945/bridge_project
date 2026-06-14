# bridge-client

OpenAI-compatible local gateway that exposes **301 AI models** from
**Arena.ai** and **Qwen** behind a single `/v1/chat/completions`
endpoint. **DeepSeek** models light up automatically once a profile
is logged into the companion `bridge-server`.

This is part of the [**lokah1945/bridge_project**](https://github.com/lokah1945/bridge_project)
gateway stack.  See `how_to_use.md` for the full architecture and
per-provider curl examples, and `model.md` for the live snapshot of
discovered models.

```
                 ┌───────────────────────────────────────┐
                 │       bridge-server  (Windows)        │
                 │  Express + persistent headfull Chrome  │
                 │  /get-session/<provider>  → cookies    │
                 └─────────────────────┬─────────────────┘
                                       │  HTTPS / ZeroTier
                                       ▼
                 ┌───────────────────────────────────────┐
                 │       bridge-client  (Linux)  ◀ YOU   │
                 │  FastAPI + Playwright (headless)       │
                 │  Fernet AES-256 session cache          │
                 │  model.json (auto-refresh 60 min)      │
                 │                                       │
                 │  GET  /health                         │
                 │  GET  /v1/models     (301 models)     │
                 │  POST /v1/chat/completions            │
                 └─────────────────────┬─────────────────┘
                                       │  headless Chromium
                                       ▼
                 ┌───────────────────────────────────────┐
                 │  arena.ai / chat.qwen.ai / chat.deepseek │
                 └───────────────────────────────────────┘
```

---

## Highlights

- ✅ **301 models** dynamically discovered across **4 providers**
  (Arena: 271 across 4 modalities, Qwen: 23 including all "Expand More"
  entries, Kimi: 4 K2.6 variants, DeepSeek: 3 fallback models pending
  login).
- ✅ **OpenAI-compatible** — works out-of-the-box with Open WebUI,
  LibreChat, Cursor, Continue, anything that speaks `/v1/chat/completions`.
- ✅ **Zero footprint** — Qwen always uses `?temporary-chat=true`,
  Arena always uses the ephemeral `/direct` endpoints, cookies are
  cleared after every request.
- ✅ **Encrypted session cache** — cookies stored as Fernet AES-256
  ciphertext (`sessions/<provider>.bin`), auto-refreshed from
  bridge-server on demand and every 24 h.
- ✅ **Background model cache** — `model.json` is refreshed every 60
  minutes by a background task; `/v1/models` is served instantly from
  disk (no scraping per request).
- ✅ **Streaming** — `stream: true` returns real OpenAI-style SSE
  chunks with `data: [DONE]`.
- ✅ **Graceful degradation** — if bridge-server is unreachable but a
  cached session exists, the gateway keeps serving from the stale
  session (logged as a WARNING).

---

## Quick start

```bash
git clone https://github.com/lokah1945/bridge_project.git
cd bridge_project/bridge-client

pip install -r requirements.txt
playwright install chromium
playwright install-deps      # fixes libnspr4.so on Debian/Ubuntu

cp .env.example .env         # adjust BRIDGE_SERVER_URL if needed
python3 client.py            # gateway listens on :8000
```

The server will:
1. Sync encrypted sessions from `BRIDGE_SERVER_URL` into `sessions/`.
2. Run dynamic model discovery on Arena (4 modalities) and Qwen, write
   results to `model.json`, and serve them via `/v1/models`.
3. Start a background task that refreshes the cache every 60 minutes.

Verify it works:

```bash
curl http://localhost:8000/health
# {"status":"ok","model_cache_updated_at":"…","providers":{…}}

curl http://localhost:8000/v1/models | jq '.data | length'
# 301
```

---

## Configuration (`.env`)

| Key | Default | Purpose |
|-----|---------|---------|
| `BRIDGE_SERVER_URL` | `http://host.zerotier.my.id:9877` | URL of the running `bridge-server` |
| `PORT` | `8000` | Local port for the FastAPI gateway |
| `ENCRYPTION_KEY` | *(auto-generated on first start)* | Fernet key for `sessions/*.bin` |
| `SESSION_TTL_HOURS` | `24` | Refresh session from bridge-server after this |
| `MODEL_CACHE_REFRESH_MINUTES` | `60` | Background refresh interval for `model.json` |
| `BROWSER_HEADLESS` | `true` | Run Chromium headless |

The first time you start the server it auto-generates `ENCRYPTION_KEY`
and persists it to `.env`.  Don't share `.env` — it contains the
decryption key for your session cookies.

---

## API

### `GET /health`

Liveness probe + cache status.

```bash
curl http://localhost:8000/health
```

```json
{
  "status": "ok",
  "model_cache_updated_at": "2026-06-14T04:59:53.664117Z",
  "providers": {"arena": "ok", "qwen": "ok", "deepseek": "NO_SESSION"}
}
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
```

### `POST /admin/login/{provider}` & `/admin/refresh/{provider}`

When a provider's session expires (e.g. DeepSeek userToken JWT goes
null, or Kimi requires re-auth via Google OAuth), the chat endpoints
return a clear error message.  Trigger a fresh login via:

```bash
# 1. Open the login URL in bridge-server's headfull Chrome
curl -X POST http://localhost:8000/admin/login/deepseek

# 2. You log in there manually (Google/email/etc.)

# 3. Pull the fresh cookies + refresh the cache
curl -X POST http://localhost:8000/admin/refresh/deepseek
```

Or use the helper script:

```bash
python3 login_helper.py deepseek   # walks you through all 3 steps
python3 login_helper.py kimi
python3 login_helper.py --list     # show all providers' status
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

---

## Architecture

`bridge-client` is the **Executor** half of the Session-Provider /
Executor-Client pattern (see `how_to_use.md` for the full diagram):

- **bridge-server** (Windows, already running): runs a headfull
  Chrome with manual login to Google / Arena / Qwen, exposes
  `/get-session/<provider>` returning the cookies + user-agent +
  headers for that provider's Web UI.
- **bridge-client** (this repo, Linux): syncs the encrypted cookies,
  then runs its own headless Chromium to drive Arena / Qwen /
  DeepSeek directly.

The server can be turned off after sync.  If a provider rejects the
session (401/403/redirect to login), the client transparently re-syncs.

### How the session cache works

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
        else if local exists:
            return local (graceful degradation, log warning)
        else:
            raise AUTH_REQUIRED → HTTP 503
```

### Statelessness / zero footprint

| Provider | Mechanism                                                |
|----------|----------------------------------------------------------|
| arena    | navigate to `/direct` (already ephemeral) + `context.clear_cookies()` after every `execute()` |
| qwen     | ALWAYS use `?temporary-chat=true` + `context.clear_cookies()` after every `execute()` |
| deepseek | `context.clear_cookies()` after every `execute()`          |

Each provider instance is created fresh per request and torn down via
`BaseProvider.cleanup()` — no leaked browser processes, no account
history pollution.

---

## Files

```
bridge-client/
├── client.py              # FastAPI gateway (entrypoint)
├── registry.py            # dynamic provider lookup + model-name parser
├── requirements.txt
├── .env.example
├── .gitignore
├── providers/
│   ├── base.py            # BaseProvider: browser lifecycle + manual CDP stealth
│   ├── arena.py           # ArenaProvider: 4 modality URLs, Radix dialog scraping
│   ├── qwen.py            # QwenProvider: Ant Design dropdown + Expand More
│   └── deepseek.py        # DeepSeekProvider: graceful NO_SESSION handling
├── test_all_models.py     # end-to-end PASS/FAIL matrix for all discovered models
├── sessions/              # auto-generated *.bin (Fernet AES-256, gitignored)
├── model.json             # dynamic model cache, refreshed every 60 min (gitignored)
├── how_to_use.md          # full architecture + per-provider curl examples
├── model.md               # snapshot of live model.json + test evidence
└── README.md              # this file
```

---

## Verified status (build host, 2026-06-14)

| Component | Status | Evidence |
|-----------|--------|----------|
| `GET /health` | ✅ PASS | `{"status":"ok", …, "providers":{"arena":"ok","qwen":"ok","deepseek":"NO_SESSION"}}` |
| `GET /v1/models` | ✅ PASS | **301 models**: arena=271 (text 135 + search 16 + image 47 + code 73), qwen=23, kimi=4, deepseek=3 (fallback) |
| `POST /v1/chat/completions` (Qwen) | ✅ PASS | HTTP 200 in 12-13 s, real AI response (`Hallo! Wie kann ich dir helfen?`) |
| `POST /v1/chat/completions` (Qwen, stream) | ✅ PASS | OpenAI-style SSE chunks + `data: [DONE]` |
| `POST /v1/chat/completions` (Kimi) | ⚠️ CLEAN_ERR | HTTP 200 with clear error in 12 s (login modal required) |
| `POST /v1/chat/completions` (DeepSeek) | ⚠️ CLEAN_ERR | HTTP 200 with clear error in 7 s (cookies stale → re-login) |
| `POST /v1/chat/completions` (Arena) | ⚠️ EMPTY | HTTP 200 but `(empty response)` — Cloudflare bot detection blocks form submission |
| Error cases (invalid model, unknown provider, empty messages) | ✅ PASS | Clean 400/404 codes, no 500s |

### Documented limitations

- **Arena execute()** — Cloudflare bot detection degrades form
  submission even with the real `cf_clearance` cookie.  The chat UI
  renders and the model list (271 models) is correctly scraped, but
  message submission is silently blocked by Cloudflare's
  degraded-mode enforcement.  `/v1/chat/completions` returns HTTP 200
  with `(empty response)` for Arena models.  See MASTER PROMPT
  Bagian 18.2 (reverse-engineering API / `playwright-extra` are
  forbidden).
- **Qwen thinking-mode models (10/23)** — the page reports
  `Thinking completed` after >130 s, which exceeds the default
  `test_all_models.py --timeout` window.  Run with `--timeout 600`
  to catch them; production requests are unbounded.
- **DeepSeek** — requires a logged-in session in bridge-server.  If
  `/get-session/deepseek` returns 404, all DeepSeek models report
  `NO_SESSION` and the gateway returns HTTP 503 with a clear message.
- **Bridge-server connectivity** — when `BRIDGE_SERVER_URL` is
  unreachable, the gateway falls back to the last-known encrypted
  session (graceful degradation, see `client.py::SessionManager`).

---

## Adding a new provider

1. Create `providers/<name>.py` with a `BaseProvider` subclass
   implementing `list_models(**kwargs)` and
   `execute(model_id, prompt, params)`.
2. Decorate the class with `@ProviderRegistry.register("<name>")`.
3. Restart the gateway — no central registry to maintain; the next
   import auto-registers the new provider.

---

## License

MIT — see project repo for details.
