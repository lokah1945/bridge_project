# bridge-server

Session Hub for [bridge-client](https://github.com/lokah1945/bridge_project/tree/bridge-client-rebuild).

Runs on **Windows** with a persistent **headfull** Chrome (one user-data-dir
shared across all providers).  When the user logs in to chat.qwen.ai,
arena.ai, www.kimi.com, or chat.deepseek.com in that Chrome, the
cookies are written to the persistent profile and become available to
bridge-client via `GET /get-session/<provider>`.

## Quick start (Windows)

```powershell
# 1. Install Python 3.10+ and Playwright
pip install -r server_requirements.txt
playwright install chromium
playwright install-deps

# 2. Run
python bridge_server.py
```

Server listens on `http://0.0.0.0:9877`.  Configure bridge-client's
`BRIDGE_SERVER_URL` to point here.

## Endpoints

| Method | Path | Purpose |
|--------|------|---------|
| GET    | `/health` | Liveness + cached cookies summary |
| GET    | `/providers` | List known providers + cache status |
| GET    | `/get-session/<provider>` | Return cookies + UA for `arena`/`qwen`/`kimi`/`deepseek` |
| POST   | `/open` (body `{"url":"..."}`) | Navigate persistent Chrome to URL (for manual login flows) |
| POST   | `/session/refresh/<provider>` | Force re-extract cookies after the user logged in |
| GET    | `/cookies/<provider>` | List cookie names+domains for a provider |

## Login flow for any provider

1. Open the page in the persistent Chrome by calling:
   ```bash
   curl -X POST http://localhost:9877/open \
     -H "Content-Type: application/json" \
     -d '{"url":"https://chat.qwen.ai/"}'
   ```
2. In the persistent Chrome window that just opened, manually log in
   (Google OAuth, email/password, etc.).
3. Wait for the chat input to appear.
4. Force-re-extract cookies by calling:
   ```bash
   curl -X POST http://localhost:9877/session/refresh/qwen
   ```
5. bridge-client will pick up the fresh cookies on its next
   `GET /get-session/<provider>` call (within ~24h TTL).

## How it works

- **Single persistent Chrome profile** (default
  `%USERPROFILE%\bridge-chrome-profile`).  All 4 providers share this
  Chromium process because the user logged into all of them in that
  browser.
- `launch_persistent_context` keeps the user-data-dir intact across
  restarts (cookies + localStorage persist).
- `GET /get-session/<provider>` returns cookies whose domain matches
  the provider's home URL (e.g. for `qwen`, returns cookies matching
  `chat.qwen.ai`).
- The persistent Chrome runs with `--remote-debugging-port=99876` so
  you can also attach DevTools from another machine if needed.

## Configuration (env vars)

| Var | Default | Purpose |
|-----|---------|---------|
| `HOST` | `0.0.0.0` | bind address |
| `PORT` | `9877` | bind port |
| `BRIDGE_USER_DATA_DIR` | `%USERPROFILE%\bridge-chrome-profile` | persistent Chrome user-data-dir |
| `HEADLESS` | `false` | run Chrome headfull (recommended) or headless |
| `REMOTE_DEBUGGING_PORT` | `99876` | Chrome DevTools port |

## Providers

| Name | Home URL |
|------|----------|
| `arena`    | https://arena.ai/text/direct |
| `qwen`     | https://chat.qwen.ai/?temporary-chat=true |
| `kimi`     | https://www.kimi.com/ |
| `deepseek` | https://chat.deepseek.com/ |

To add a new provider: append to `PROVIDERS` in `bridge_server.py` and
update bridge-client's `LOGIN_URLS` / `PROVIDER_FALLBACKS` accordingly.
