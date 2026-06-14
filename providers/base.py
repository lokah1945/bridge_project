"""BaseProvider — common browser lifecycle + manual CDP stealth.

Reference implementation per MASTER PROMPT Bagian 8.  Stealth is implemented
manually via CDP ``Page.addScriptToEvaluateOnNewDocument`` and
``Network.setExtraHTTPHeaders``; we deliberately avoid ``playwright-extra``
and ``playwright_stealth`` (see Bagian 18 poin 1).
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

from playwright.async_api import BrowserContext, Page, async_playwright

logger = logging.getLogger("bridge.base")

DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

# JS payload applied before any page script runs.
STEALTH_SCRIPT = """
    Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
    Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en'] });
    Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
    Object.defineProperty(window, 'chrome', {
        get: () => ({
            runtime: {},
            app: { isInstalled: false },
            csi: () => ({}),
            loadTimes: () => ({}),
        })
    });
    const _origQuery = window.navigator.permissions && window.navigator.permissions.query;
    if (_origQuery) {
        window.navigator.permissions.query = (p) =>
            p && p.name === 'notifications'
                ? Promise.resolve({ state: Notification.permission })
                : _origQuery(p);
    }
    Object.defineProperty(navigator, 'maxTouchPoints', { get: () => 0 });
    Object.defineProperty(navigator, 'platform', { get: () => 'Win32' });
"""

# Extra headers that nudge navigator.userAgentData-style heuristics.
STEALTH_HEADERS = {
    "sec-ch-ua": '"Chromium";v="124", "Google Chrome";v="124", "Not-A.Brand";v="99"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"Windows"',
    "sec-ch-ua-platform-version": '"15.0.0"',
}


class BaseProvider(ABC):
    """Abstract base for all AI provider automations."""

    #: name used for registry lookup (overridden in subclasses).
    name: str = "base"

    def __init__(self, session_data: Optional[Dict[str, Any]] = None):
        self.session_data = session_data or {}
        self.cookies: List[Dict[str, Any]] = self.session_data.get("cookies", []) or []
        self.user_agent: str = self.session_data.get("user_agent") or DEFAULT_UA
        self.headers: Dict[str, str] = self.session_data.get("headers") or {}
        self.playwright = None
        self.browser = None
        self.context: Optional[BrowserContext] = None
        self._owns_browser = True

    # ------------------------------------------------------------------ browser

    async def setup_browser(self) -> Page:
        """Launch Playwright headless Chromium, inject cookies, return a Page."""
        if not self.browser:
            self.playwright = await async_playwright().start()
            self.browser = await self.playwright.chromium.launch(
                headless=True,
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--no-sandbox",
                ],
            )
            ctx_kwargs: Dict[str, Any] = {
                "user_agent": self.user_agent,
                "viewport": {"width": 1366, "height": 768},
                "locale": "en-US",
                "timezone_id": "Asia/Jakarta",
            }
            # forward Accept-Language if server supplied one.
            if "Accept-Language" in self.headers:
                ctx_kwargs["locale"] = self.headers["Accept-Language"].split(",")[0]

            self.context = await self.browser.new_context(**ctx_kwargs)

            if self.headers:
                try:
                    await self.context.set_extra_http_headers(
                        {**STEALTH_HEADERS, **self.headers}
                    )
                except Exception as exc:  # pragma: no cover - defensive
                    logger.warning("set_extra_http_headers failed: %s", exc)

            if self.cookies:
                # cookies from /get-session/* may carry `partitionKey` and other
                # unsupported keys — strip them defensively.
                clean: List[Dict[str, Any]] = []
                for c in self.cookies:
                    clean.append(
                        {
                            k: v
                            for k, v in c.items()
                            if k
                            in (
                                "name",
                                "value",
                                "domain",
                                "path",
                                "expires",
                                "httpOnly",
                                "secure",
                                "sameSite",
                                "url",
                            )
                        }
                    )
                try:
                    await self.context.add_cookies(clean)
                except Exception as exc:
                    logger.warning("add_cookies failed: %s", exc)

        if not getattr(self, "_page", None) or self._page.is_closed():
            page = await self.context.new_page()
            self._page = page
        else:
            page = self._page

        # Manual CDP stealth applied per-page so it sticks to every navigation.
        try:
            cdp = await page.context.new_cdp_session(page)  # NOTE: context is a property
            await cdp.send(
                "Page.addScriptToEvaluateOnNewDocument",
                {"source": STEALTH_SCRIPT},
            )
            await cdp.send(
                "Network.setExtraHTTPHeaders",
                {"headers": STEALTH_HEADERS},
            )
        except Exception as exc:
            logger.warning("CDP stealth setup failed (continuing): %s", exc)

        return page

    async def cleanup(self) -> None:
        """Close the browser.  Always invoked from a finally block."""
        try:
            if getattr(self, "_page", None) and not self._page.is_closed():
                await self._page.close()
            self._page = None
        except Exception:
            pass
        try:
            if self.browser:
                await self.browser.close()
        except Exception:
            pass
        try:
            if self.playwright:
                await self.playwright.stop()
        except Exception:
            pass
        self.browser = None
        self.playwright = None
        self.context = None

    # ------------------------------------------------------------------ helpers

    async def clear_context_cookies(self) -> None:
        if self.context:
            try:
                await self.context.clear_cookies()
            except Exception as exc:  # pragma: no cover
                logger.debug("clear_cookies failed: %s", exc)

    # ------------------------------------------------------------------ abstract

    @abstractmethod
    async def list_models(self, **kwargs) -> Any:
        ...

    @abstractmethod
    async def execute(self, model_id: str, prompt: str, params: Dict[str, Any]) -> str:
        ...
