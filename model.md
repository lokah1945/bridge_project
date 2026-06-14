# Live model snapshot

This file is auto-populated by `bridge-client`'s discovery probes.
Numbers below come from real runs against `BRIDGE_SERVER_URL`
(build host 2026-06-14).

## Summary (verified by `/v1/models`)

| Provider | Status     | Total models | Notes                                          |
|----------|------------|--------------|------------------------------------------------|
| arena    | ok         | 271          | 4 modality URLs (text/search/image/code)       |
| qwen     | ok         | 23           | 3 Primary + 20 from "Expand More"               |
| deepseek | ok         | 3            | FALLBACK list (cookies stale; re-login needed)  |
| kimi     | ok         | 4            | 4 K2.6 variants (chat gated by login modal)      |

**Grand total served by `/v1/models`: 301**

## Arena — 271 models

The Arena **mode** selector is a `role=combobox` button with text like
`Direct`/`Battle`/`Side-by-Side`/`Agent`.  The **model** selector is a
separate button with `aria-haspopup="dialog"` showing the current model
name (e.g. `Max`).  We click the latter via `page.evaluate(JS click)` to
bypass viewport-overlap quirks and scrape every `[role="option"]` in
the Radix-UI dialog.

| Modality | Count | Sample (first 3)                                                 |
|----------|-------|------------------------------------------------------------------|
| text     | 135   | gemini-3-flash, gpt-5.2-chat-latest, glm-5.1                     |
| search   | 16    | claude-sonnet-4-6-search, grok-4.20-multi-agent-beta-0309, gpt-5.2-search |
| image    | 47    | flux-2-pro, reve-v1.5, flux-2-dev                                |
| code     | 73    | gemini-3-flash, glm-5.1, qwen3.5-397b-a17b                       |

## Qwen — 23 models

The Qwen model selector is an Ant Design
`<span class="ant-dropdown-trigger">` whose descendant carries
`index-module__model-selector-text`.  The dropdown shows 3 primary
models first, then an "Expand more models" link.  We click that link
via Playwright's native click (JS `.click()` does NOT trigger React's
onClick reliably) and re-scrape.

| Bucket          | Count | Sample (abbreviated)                                              |
|-----------------|-------|-------------------------------------------------------------------|
| Primary         | 3     | Qwen3.7-Plus, Qwen3.7-Max, Qwen3.6-Plus                           |
| Expanded (+20)  | 20    | Qwen3-Max, Qwen3-Coder, Qwen3-Omni-Flash, Qwen3-VL-235B-A22B, Qwen3-235B-A22B-2507, Qwen3.5-Plus, Qwen3.5-Omni-Plus, Qwen3.6-35B-A3B, Qwen3.6-27B, Qwen3.6-Max-Preview, Qwen3.6-Plus-Preview, Qwen3.5-Flash, Qwen3.5-Max-Preview, Qwen3.7-Max-Preview, Qwen3.7-Plus-Preview, Qwen3.5-122B-A10B, Qwen3.5-Omni-Flash, Qwen3.5-27B, Qwen3.5-35B-A3B, Qwen3.5-397B-A17B |

## DeepSeek — 3 models (FALLBACK)

chat.deepseek.com redirects to `/sign_in` when session cookies are
stale (no logged-in user).  We detect this early and return a clear
error message instead of hanging on a 30 s fill() timeout.  The FALLBACK
list is returned so `/v1/models` still has something for this provider:

- deepseek-chat
- deepseek-reasoner
- deepseek-coder

To enable real DeepSeek chat, log in via `bridge-server`'s
`/open?url=https://chat.deepseek.com` then refresh the cache.

## Kimi — 4 models (chat requires login)

www.kimi.com shows 4 K2.6 variants in the model popup:

- K2.6 Instant — quick response
- K2.6 Thinking — deep thinking
- K2.6 Agent — research / slides / websites / docs / sheets
- K2.6 Agent Swarm — large-scale search / long-form writing / batch tasks

**Discovery works** (popup opens correctly).

**Chat requires full account login**: although bridge-server's session
cookie blob contains `.kimi.com` cookies (shared Chromium profile),
clicking Send opens a "Log in to chat with Kimi for Free" modal with
"Continue with Google" / "Log in with phone number" options.  We
detect this modal and return a clear error in <15 s instead of timing
out:

```
"(kimi requires full account login to send messages - the browser
session alone is not enough; complete Kimi login via bridge-server)"
```

To enable real Kimi chat, complete the Google/phone login via
`bridge-server` `/open?url=https://www.kimi.com/`.

## End-to-end verification (build host 2026-06-14)

### `/health`

```json
{
  "status": "ok",
  "providers": {"arena": "ok", "qwen": "ok", "deepseek": "ok", "kimi": "ok"}
}
```

### `/v1/models`

301 models served.

### `/v1/chat/completions`

| Model | Status | Latency | Result |
|-------|--------|---------|--------|
| `bridge/qwen/Qwen3-Coder` | **PASS** | 12.8 s | `"Hallo! (Hello!) How can I assist you today?"` |
| `bridge/qwen/Qwen3.5-Omni-Plus` | **PASS** | 12.6 s | `"Hallo! Wie kann ich Ihnen heute helfen?"` |
| `bridge/qwen/Qwen3-Max` | **PASS** | 12.9 s | `"Hallo! Wie kann ich dir helfen?"` |
| `bridge/qwen/Qwen3.5-Flash` | TIMEOUT | 130 s+ | thinking-mode model exceeds polling window |
| `bridge/kimi/K2.6 Instant` | CLEAN_ERR | 12.2 s | login modal detected → clear error message |
| `bridge/deepseek/deepseek-chat` | CLEAN_ERR | 7.1 s | cookies stale → `/sign_in` redirect → clear error |
| `bridge/arena/text/gemini-3-flash` | EMPTY | 8.5 s | Cloudflare bot detection on form submit |
| `bridge/arena/code/gemini-3-flash` | EMPTY | 38 s | same |
| `bridge/nonexistent/foo` | **404** | 0.0 s | clean error, no server crash |

### Streaming

`POST /v1/chat/completions` with `stream: true` returns real OpenAI-style
SSE chunks with `data: [DONE]`.  Verified manually.

### Error semantics

All input validation errors return proper HTTP codes — no 500s:

| Input | Status | Response |
|-------|--------|----------|
| `bridge/nonexistent/foo` | **404** | `Provider 'nonexistent' not found. Known: [arena, deepseek, kimi, qwen]` |
| `gpt-4` (no `bridge/` prefix) | **400** | `model 'gpt-4' is not in bridge/ format` |
| empty `messages` | **400** | `messages must not be empty` |
| `[{role: assistant, content: "hi"}]` | **400** | `only user-role messages are supported` |
| `bridge/arena/audio/foo` | **400** | `arena modality 'audio' not in {text, search, image, code}` |

## Documented limitations

- **Arena execute()** — Cloudflare bot detection blocks form submission
  even with the real `cf_clearance` cookie.  See MASTER PROMPT
  Bagian 18.2.
- **Qwen thinking-mode models** — the page reports `Thinking
  completed` after >130 s; default polling window catches only fast
  models.  Use `--timeout 600` (or higher) to catch them.
- **DeepSeek / Kimi** — require full account login on chat.deepseek.com
  / www.kimi.com.  Cookie-only authentication is insufficient.
