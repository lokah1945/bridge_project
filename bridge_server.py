"""bridge-server — Session Hub for bridge-client.

Runs on Windows with a persistent headfull Chrome (single profile).  When
the user logs in to chat.qwen.ai, arena.ai, www.kimi.com, chat.deepseek.com
in that Chrome, the cookies are written to the persistent user-data-dir
and become available to bridge-client via /get-session/<provider>.

Endpoints
---------
GET  /health                              liveness check
GET  /get-session/<provider>             return cookies+UA for that provider
                                          (provider = arena | qwen | kimi | deepseek)
POST /open                                navigate persistent Chrome to URL (for
         body: {"url": "https://..."}      manual login flows)
POST /session/refresh/<provider>         force-extract cookies from the
                                          persistent Chrome and cache them
                                          under the provider name
GET  /providers                           list known providers + status
GET  /cookies/<provider>                  list cookie names+domains for a provider

Design notes
------------
- Single persistent Chrome profile (user-data-dir).  All 4 providers
  share the same Chromium process because the user logged into all of
  them via that browser.  This matches what users do in practice.
- /get-session reads from an in-memory cache that is populated by:
  * the initial startup probe (visits each provider's home page to
    trigger the JS cookie/localStorage hydration), OR
  * an explicit /session/refresh/<provider> call.
- /open is fire-and-forget: the request returns immediately, but the
  persistent Chrome navigates in the background.  The user has to
  manually complete the login in that browser.
- Cookies are returned as-is (no encryption server-side — the client
  encrypts with Fernet AES-256 before writing to disk).
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, Response
from playwright.async_api import async_playwright, Browser, BrowserContext, Page

# --------------------------------------------------------------------- config

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s | %(message)s",
)
logger = logging.getLogger("bridge.server")

HOST = os.environ.get("HOST", "0.0.0.0")
PORT = int(os.environ.get("PORT", "9877"))

# Persistent Chrome user-data-dir.  All cookies live here.
USER_DATA_DIR = os.environ.get(
    "BRIDGE_USER_DATA_DIR",
    str(Path.home() / "bridge-chrome-profile"),
)

# Playwright launch args.
HEADLESS = os.environ.get("HEADLESS", "false").lower() in ("1", "true", "yes")
REMOTE_DEBUGGING_PORT = int(os.environ.get("REMOTE_DEBUGGING_PORT", "99876"))

# Providers we know about.
PROVIDERS: Dict[str, Dict[str, str]] = {
    "arena":    {"home": "https://arena.ai/text/direct"},
    "qwen":     {"home": "https://chat.qwen.ai/?temporary-chat=true"},
    "kimi":     {"home": "https://www.kimi.com/"},
    "deepseek": {"home": "https://chat.deepseek.com/"},
}


# ===================================================================== state

class BridgeState:
    """Holds the persistent browser, in-memory cookie cache, etc."""

    def __init__(self) -> None:
        self.playwright = None
        self.browser: Optional[Browser] = None
        self.context: Optional[BrowserContext] = None
        # provider -> {cookies, user_agent, headers, updated_at}
        self.cache: Dict[str, Dict[str, Any]] = {}
        self.lock = asyncio.Lock()

    async def launch(self) -> None:
        """Launch the persistent headfull (or headless) Chrome.

        On Windows just run as-is.  On Linux without a display, you can
        either set ``HEADLESS=true`` or wrap with ``xvfb-run``:
            xvfb-run -a python bridge_server.py
        """
        Path(USER_DATA_DIR).mkdir(parents=True, exist_ok=True)
        self.playwright = await async_playwright().start()
        # Use launch_persistent_context so the user-data-dir is the same
        # across restarts (cookies + localStorage persist).
        effective_headless = HEADLESS or self._should_force_headless()
        args = [
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-blink-features=AutomationControlled",
        ]
        # remote-debugging-port is only valid in headed mode (the headless
        # shell rejects it).
        if not effective_headless:
            args.append(f"--remote-debugging-port={REMOTE_DEBUGGING_PORT}")
        logger.info(
            "launching persistent Chrome (user_data_dir=%s, headless=%s)",
            USER_DATA_DIR, effective_headless,
        )
        self.context = await self.playwright.chromium.launch_persistent_context(
            user_data_dir=USER_DATA_DIR,
            headless=effective_headless,
            args=args,
            # Default viewport; the user can resize the window manually.
            viewport={"width": 1366, "height": 768},
            locale="en-US",
            no_viewport=False,
        )
        self.browser = self.context.browser  # may be None on persistent
        logger.info("persistent Chrome launched (headless=%s) on remote-debugging-port=%s",
                    effective_headless, REMOTE_DEBUGGING_PORT)

    @staticmethod
    def _should_force_headless() -> bool:
        """Linux without DISPLAY?  Force headless so Chrome doesn't crash."""
        if os.name != "posix":
            return False
        if os.environ.get("DISPLAY"):
            return False
        if os.environ.get("FORCE_HEADED"):
            return False
        return True

    async def shutdown(self) -> None:
        try:
            if self.context:
                await self.context.close()
        except Exception:
            pass
        try:
            if self.playwright:
                await self.playwright.stop()
        except Exception:
            pass

    async def open_url(self, url: str) -> None:
        """Navigate the persistent Chrome's first page to ``url``."""
        if not self.context:
            raise RuntimeError("Chrome not launched")
        # If there are no pages, open one.  Otherwise reuse the first one.
        if not self.context.pages:
            page = await self.context.new_page()
        else:
            page = self.context.pages[0]
        logger.info("navigating persistent Chrome to %s", url)
        await page.goto(url, wait_until="domcontentloaded", timeout=60000)

    async def refresh_session(self, provider: str) -> Dict[str, Any]:
        """Extract cookies + UA for a provider from the persistent Chrome.

        Strategy:
          1. Open the provider's home URL in a fresh page.
          2. Wait for the page to settle (networkidle / 5 s).
          3. Collect all cookies whose domain matches this provider's
             home URL (plus sub-domains).
          4. Capture user_agent from the page context.
        """
        if provider not in PROVIDERS:
            raise ValueError(f"unknown provider {provider!r}")
        home = PROVIDERS[provider]["home"]
        from urllib.parse import urlparse
        host = urlparse(home).hostname  # e.g. "chat.qwen.ai" or "www.kimi.com"

        if not self.context:
            raise RuntimeError("Chrome not launched")

        page = await self.context.new_page()
        try:
            await page.goto(home, wait_until="domcontentloaded", timeout=60000)
            # Wait for JS cookie hydration (chat.qwen.ai sets via XHR, etc.)
            try:
                await page.wait_for_load_state("networkidle", timeout=15000)
            except Exception:
                pass
            await asyncio.sleep(2.0)
            # Collect all cookies from this context, filter by host.
            all_cookies = await self.context.cookies()
            kept: List[Dict[str, Any]] = []
            host_no_dot = host.lstrip(".")
            for c in all_cookies:
                domain = (c.get("domain") or "").lstrip(".")
                # Match exact or any subdomain
                if domain == host_no_dot or domain.endswith("." + host_no_dot):
                    kept.append(c)
            user_agent = await page.evaluate("() => navigator.userAgent")
            payload = {
                "cookies": kept,
                "user_agent": user_agent,
                "headers": {
                    "Accept-Language": "en-US,en;q=0.9",
                },
                "home_url": home,
                "updated_at": time.time(),
            }
            async with self.lock:
                self.cache[provider] = payload
            logger.info(
                "refreshed session for %s: %d cookies (out of %d total)",
                provider, len(kept), len(all_cookies),
            )
            return payload
        finally:
            try:
                await page.close()
            except Exception:
                pass


state = BridgeState()


# ===================================================================== FastAPI

from contextlib import asynccontextmanager


@asynccontextmanager
async def lifespan(_app: FastAPI):
    await state.launch()
    # Best-effort: refresh sessions for all providers in the background.
    asyncio.create_task(_refresh_all_providers())
    yield
    await state.shutdown()


app = FastAPI(title="bridge-server", version="1.0.0", lifespan=lifespan)


async def _refresh_all_providers() -> None:
    """Wait a bit, then refresh all 4 providers."""
    await asyncio.sleep(3)
    for prov in PROVIDERS:
        try:
            await state.refresh_session(prov)
        except Exception as exc:
            logger.warning("startup refresh for %s failed: %s", prov, exc)


# ---------------------------------------------- GET /health

@app.get("/health")
async def health() -> Dict[str, Any]:
    return {
        "status": "online",
        "providers": {
            p: {
                "cached": p in state.cache,
                "cookie_count": len(state.cache.get(p, {}).get("cookies", [])),
                "updated_at": state.cache.get(p, {}).get("updated_at"),
            }
            for p in PROVIDERS
        },
    }


# --------------------------------------------- GET /get-session/<provider>

@app.get("/get-session/{provider}")
async def get_session(provider: str) -> Dict[str, Any]:
    p = provider.lower()
    if p not in PROVIDERS:
        raise HTTPException(
            status_code=404,
            detail=f"unknown provider {provider!r}; known: {list(PROVIDERS)}",
        )
    async with state.lock:
        cached = state.cache.get(p)
    if cached is None:
        # First call: extract on demand.
        try:
            cached = await state.refresh_session(p)
        except Exception as exc:
            logger.warning("lazy refresh for %s failed: %s", p, exc)
            raise HTTPException(
                status_code=503,
                detail=(
                    f"session not yet cached for {p!r} and lazy refresh failed: {exc}.  "
                    f"Try POST /session/refresh/{p} after logging in via /open."
                ),
            )
    return cached


# --------------------------------------------- POST /open  (navigate Chrome)

@app.post("/open")
async def open_url(request: Request) -> Dict[str, Any]:
    body = await request.json()
    url = body.get("url") if isinstance(body, dict) else None
    if not url:
        raise HTTPException(status_code=400, detail="body must include 'url'")
    try:
        await state.open_url(url)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    return {"status": "navigated", "url": url}


# --------------------------------------------- POST /session/refresh/<provider>

@app.post("/session/refresh/{provider}")
async def refresh_session(provider: str) -> Dict[str, Any]:
    p = provider.lower()
    if p not in PROVIDERS:
        raise HTTPException(
            status_code=404,
            detail=f"unknown provider {provider!r}; known: {list(PROVIDERS)}",
        )
    try:
        payload = await state.refresh_session(p)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    return {
        "status": "refreshed",
        "provider": p,
        "cookie_count": len(payload["cookies"]),
        "user_agent": payload["user_agent"],
    }


# --------------------------------------------- GET /providers

@app.get("/providers")
async def list_providers() -> Dict[str, Any]:
    return {
        "providers": list(PROVIDERS),
        "details": {
            p: {
                "home": PROVIDERS[p]["home"],
                "cached": p in state.cache,
                "cookie_count": len(state.cache.get(p, {}).get("cookies", [])),
                "user_agent": state.cache.get(p, {}).get("user_agent"),
                "updated_at": state.cache.get(p, {}).get("updated_at"),
            }
            for p in PROVIDERS
        },
    }


# --------------------------------------------- GET /cookies/<provider>

@app.get("/cookies/{provider}")
async def list_cookies(provider: str) -> Dict[str, Any]:
    p = provider.lower()
    async with state.lock:
        cached = state.cache.get(p)
    if not cached:
        raise HTTPException(status_code=404, detail=f"no cached cookies for {p!r}")
    return {
        "provider": p,
        "cookies": [
            {"name": c["name"], "domain": c.get("domain"), "path": c.get("path")}
            for c in cached.get("cookies", [])
        ],
        "count": len(cached.get("cookies", [])),
    }


# --------------------------------------------- entry

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=HOST, port=PORT, log_level="info")
