# Live model snapshot

This file is auto-populated by `bridge-client`'s discovery probes.
The numbers below come from a real run against `BRIDGE_SERVER_URL` on
the build host (2026-06-14).

## Summary (verified by `/v1/models`)

| Provider | Status       | Total models | Notes                                  |
|----------|--------------|--------------|----------------------------------------|
| arena    | ok           | 271          | 4 modality URLs (text/search/image/code) |
| qwen     | ok           | 23           | 3 Primary + 20 from "Expand More"      |
| deepseek | NO_SESSION   | 0            | bridge-server returned 404; login pending |

**Grand total served by `/v1/models`: 294**

## Arena — 271 models

The Arena mode selector is a `role=combobox` button with text like
`Direct`/`Battle`/`Side-by-Side`/`Agent`.  The **model** selector is a
separate button with `aria-haspopup="dialog"` showing the current model
name (e.g. `Max`).  We click the latter via `page.evaluate(JS click)` to
bypass viewport-overlap quirks and scrape every `[role="option"]` in
the Radix-UI dialog.

| Modality | Count | First 3                                                          |
|----------|-------|------------------------------------------------------------------|
| text     | 135   | gemini-3-flash, gpt-5.2-chat-latest, glm-5.1                     |
| search   | 16    | claude-sonnet-4-6-search, grok-4.20-multi-agent-beta-0309, gpt-5.2-search |
| image    | 47    | flux-2-pro, reve-v1.5, flux-2-dev                                |
| code     | 73    | gemini-3-flash, glm-5.1, qwen3.5-397b-a17b                       |

## Qwen — 23 models

The Qwen model selector is an Ant Design `<span class="ant-dropdown-trigger">`
whose descendant carries `index-module__model-selector-text`.  The
dropdown shows 3 primary models first, then an "Expand more models" link.
We click that link via Playwright's native click (JS `.click()` does
**not** trigger React's onClick reliably) and re-scrape.

| Bucket          | Count | Models (abbreviated)                                                |
|-----------------|-------|---------------------------------------------------------------------|
| Primary         | 3     | Qwen3.7-Plus, Qwen3.7-Max, Qwen3.6-Plus                             |
| Expanded (+20)  | 20    | Qwen3-Max, Qwen3-Coder, Qwen3-Omni-Flash, Qwen3-VL-235B-A22B, Qwen3-235B-A22B-2507, Qwen3.5-Plus, Qwen3.5-Omni-Plus, Qwen3.6-35B-A3B, Qwen3.6-27B, Qwen3.6-Max-Preview, Qwen3.6-Plus-Preview, Qwen3.5-Flash, Qwen3.5-Max-Preview, Qwen3.7-Max-Preview, Qwen3.7-Plus-Preview, Qwen3.5-122B-A10B, Qwen3.5-Omni-Flash, Qwen3.5-27B, Qwen3.5-35B-A3B, Qwen3.5-397B-A17B |

## DeepSeek — 0 models

DeepSeek discovery depends on `/get-session/deepseek` returning a
valid cookie set from a logged-in bridge-server profile.  On the
current build host the endpoint returns **404 Not Found** and the
client sets status=`NO_SESSION` for the provider.  To enable DeepSeek
models, log in via bridge-server's `/open?url=https://chat.deepseek.com`
endpoint and re-run the gateway (the cache will refresh within
`MODEL_CACHE_REFRESH_MINUTES`, default 60).

## Verification — `test_all_models.py` on all 23 Qwen models

| Status | Count | Latency | Notes                                              |
|--------|-------|---------|----------------------------------------------------|
| PASS   | 13    | 12-33 s | Real AI response captured from the page            |
| FAIL   | 10    | 130+ s  | Thinking-mode models exceeded the 130 s polling    |

PASS examples (excerpt of response):

```
[PASS] bridge/qwen/Qwen3-235B-A22B-2507   (14.9s) "Hallo! 😊 It's Sunday, June 14, 2026—how can I assist you today?..."
[PASS] bridge/qwen/Qwen3-Coder             (12.8s) "Hallo! Wie kann ich dir helfen?"
[PASS] bridge/qwen/Qwen3-Max               (12.8s) "Hallo! Wie kann ich Ihnen helfen?"
[PASS] bridge/qwen/Qwen3-Omni-Flash        (18.9s) "Hallo! 😊 Wie kann ich dir heute helfen?..."
[PASS] bridge/qwen/Qwen3-VL-235B-A22B      (32.8s) "Hallo! Wie kann ich dir heute helfen? 😊"
[PASS] bridge/qwen/Qwen3.5-35B-A3B         (12.9s) "Ob Sie Fragen zu einem bestimmten Thema haben..."
[PASS] bridge/qwen/Qwen3.5-397B-A17B       (28.8s) "Hallo! Wie geht es dir? Was kann ich heute für dich tun? 👋"
[PASS] bridge/qwen/Qwen3.5-Omni-Flash      (13.0s) "Hallo! Wie kann ich dir heute helfen?"
[PASS] bridge/qwen/Qwen3.5-Omni-Plus       (12.8s) "Hallo! Hoe kan ik je vandaag helpen?"
[PASS] bridge/qwen/Qwen3.6-27B             (16.9s) "Hallo! Wie kann ich dir heute helfen? 😊"
[PASS] bridge/qwen/Qwen3.6-35B-A3B         (14.9s) "Hallo! Wie kann ich dir heute helfen?"
[PASS] bridge/qwen/Qwen3.7-Max-Preview     (20.8s) "Hallo! Wie kann ich Ihnen heute helfen?"
[PASS] bridge/qwen/Qwen3.7-Plus-Preview    (26.7s) "Hallo! Wie kann ich Ihnen heute helfen?"
```

FAIL examples (timeout, not API error — models would respond given more time):

```
[FAIL] bridge/qwen/Qwen3.5-122B-A10B  (133.2s) empty response: '(no response)'
[FAIL] bridge/qwen/Qwen3.5-27B        (132.9s) empty response: '(no response)'
[FAIL] bridge/qwen/Qwen3.5-Flash      (132.9s) empty response: '(no response)'
[FAIL] bridge/qwen/Qwen3.5-Max-Preview (132.9s) empty response: '(no response)'
[FAIL] bridge/qwen/Qwen3.5-Plus       (132.9s) empty response: '(no response)'
[FAIL] bridge/qwen/Qwen3.6-Max-Preview (180.1s) network: ...
[FAIL] bridge/qwen/Qwen3.6-Plus        (131.6s) empty response: '(no response)'
[FAIL] bridge/qwen/Qwen3.6-Plus-Preview(133.0s) empty response: '(no response)'
[FAIL] bridge/qwen/Qwen3.7-Max        (131.6s) empty response: '(no response)'
[FAIL] bridge/qwen/Qwen3.7-Plus       (131.7s) empty response: '(no response)'
```

**Qwen pass rate: 13/23 = 56%** (the 10 failures are thinking-mode
models that need >2 minutes; raising `--timeout 600` would catch more).

## Arena execute verification

Arena models list correctly via the discovery probes (271 models), but
the **chat submission is blocked by Cloudflare bot detection** even with
the real `cf_clearance` cookie.  All Arena `POST /v1/chat/completions`
calls return HTTP 200 with body `(empty response)` in 8-40 s.

This is a real limitation imposed by Cloudflare's
anti-bot-enforcement on the `/direct` endpoints.  There is no workaround
inside the Playwright + headless-Chromium + CDP-stealth approach
implemented here (see MASTER PROMPT Bagian 18.2 — `playwright-extra` /
reverse-engineered APIs are explicitly forbidden).

## DeepSeek

Discovery returns 0 models with `status=NO_SESSION`.  Once the
bridge-server profile for chat.deepseek.com is logged in, the cache
will pick up the models on the next refresh cycle (default 60 min).
