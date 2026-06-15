"""Bridge-Server (Python/FastAPI) — Alternative Session Hub.

This is a Python-based alternative to `server/server.js`. It runs a headfull
browser on Windows and exposes:
  GET /get-session/{provider}
  POST /invoke
  GET /health

The browser context is kept alive so cookies remain valid. The recommended
Windows server is `server/server.js` (Node.js) because it can use the full
puppeteer-extra-plugin-stealth stack. Use this Python server only if you
prefer a Python-only environment.
"""
import json
import os
from typing import Any, Dict

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from dotenv import load_dotenv
from playwright.async_api import async_playwright
from playwright_stealth import Stealth

load_dotenv()

PORT = int(os.getenv("BRIDGE_SERVER_PORT", 99876))
REMOTE_DEBUG_PORT = int(os.getenv("REMOTE_DEBUG_PORT", 99876))
HEADLESS = os.getenv("BROWSER_HEADLESS", "false").lower() in ("true", "1", "yes")

app = FastAPI(title="Bridge-Server Hub (Python)")

_DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

browser_context: Dict[str, Any] = {
    "playwright": None,
    "browser": None,
    "context": None,
    "sessions": {
        "arena": {
            "cookies": [],
            "user_agent": _DEFAULT_USER_AGENT,
            "headers": {"Accept-Language": "en-US,en;q=0.9"},
        },
        "qwen": {
            "cookies": [],
            "user_agent": _DEFAULT_USER_AGENT,
            "headers": {"Accept-Language": "en-US,en;q=0.9"},
        },
        "deepseek": {
            "cookies": [],
            "user_agent": _DEFAULT_USER_AGENT,
            "headers": {"Accept-Language": "en-US,en;q=0.9"},
        },
    },
}


@app.on_event("startup")
async def startup():
    pw = await async_playwright().start()
    browser = await pw.chromium.launch(
        headless=HEADLESS,
        args=[
            f"--remote-debugging-port={REMOTE_DEBUG_PORT}",
            "--start-maximized",
            "--disable-blink-features=AutomationControlled",
        ],
    )
    context = await browser.new_context(
        user_agent=_DEFAULT_USER_AGENT,
        viewport=None,
        locale="en-US",
        timezone_id="America/New_York",
    )
    await Stealth().apply_stealth_async(context)

    browser_context["playwright"] = pw
    browser_context["browser"] = browser
    browser_context["context"] = context
    print(f"[Bridge-Server] Python hub started on port {PORT}. Browser active on port {REMOTE_DEBUG_PORT}.")


@app.on_event("shutdown")
async def shutdown():
    if browser_context["context"]:
        await browser_context["context"].close()
    if browser_context["browser"]:
        await browser_context["browser"].close()
    if browser_context["playwright"]:
        await browser_context["playwright"].stop()
    print("[Bridge-Server] Python hub stopped.")


@app.get("/health")
async def health():
    return {
        "status": "online",
        "browser_ready": browser_context["browser"] is not None,
        "providers": list(browser_context["sessions"].keys()),
    }


@app.get("/get-session/{provider}")
async def get_session(provider: str):
    provider = provider.lower()
    if provider not in browser_context["sessions"]:
        raise HTTPException(status_code=404, detail=f"Provider session '{provider}' not found")

    ctx = browser_context["context"]
    if ctx is None:
        raise HTTPException(status_code=503, detail="Browser context not ready")

    cookies = await ctx.cookies()
    browser_context["sessions"][provider]["cookies"] = cookies
    return browser_context["sessions"][provider]


@app.post("/invoke")
async def invoke_bridge(request: Request):
    """Direct invocation endpoint (used mostly for testing)."""
    # Lazy import to avoid loading client-side browser automation on startup.
    from registry import registry
    from providers.arena import ArenaProvider
    from providers.qwen import QwenProvider
    from providers.deepseek import DeepSeekProvider

    registry.register("arena", ArenaProvider)
    registry.register("qwen", QwenProvider)
    registry.register("deepseek", DeepSeekProvider)

    body = await request.json()
    target = body.get("target")
    payload = body.get("payload", {})

    if not target or "/" not in target:
        raise HTTPException(status_code=400, detail="Invalid target format. Use bridge/provider/model")

    parts = target.split("/")
    if parts[0] != "bridge" or len(parts) < 3:
        raise HTTPException(status_code=400, detail="Invalid naming convention")

    provider_name = parts[1]
    model_id = parts[2]

    provider_class = registry.get_provider_class(provider_name)
    if not provider_class:
        raise HTTPException(status_code=404, detail=f"Provider '{provider_name}' not found")

    session_data = browser_context["sessions"].get(provider_name, {})
    provider_instance = provider_class(session_data)

    try:
        result = await provider_instance.execute(model_id, payload.get("prompt", ""), payload)
        return {"result": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        await provider_instance.cleanup()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=PORT)
