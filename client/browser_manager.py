"""Browser lifecycle manager for bridge-client.

Design: one shared Playwright browser instance, one fresh context per request.
Each context is isolated (cookies, localStorage, cache) and is closed after the
provider finishes, so state never leaks between requests.
"""
import asyncio
from typing import Any, Dict, List, Optional

from playwright.async_api import async_playwright, Browser, BrowserContext, Page
from playwright_stealth import Stealth

from client.config import settings


# Global browser singleton state.
_pw = None
_browser: Optional[Browser] = None
_lock = asyncio.Lock()


async def _ensure_browser() -> Browser:
    """Lazy-initialize the shared Playwright browser instance."""
    global _pw, _browser
    if _browser is not None and not _browser.is_closed():
        return _browser

    async with _lock:
        if _browser is not None and not _browser.is_closed():
            return _browser

        _pw = await async_playwright().start()
        _browser = await _pw.chromium.launch(
            headless=settings.headless,
            args=[
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-blink-features=AutomationControlled",
                "--disable-web-security",
                "--disable-features=IsolateOrigins,site-per-process",
            ],
        )
        return _browser


async def new_context(session_data: Optional[Dict[str, Any]] = None) -> BrowserContext:
    """Create a new isolated browser context with stealth and session injection."""
    browser = await _ensure_browser()
    session_data = session_data or {}

    user_agent = session_data.get("user_agent") or (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )

    context = await browser.new_context(
        user_agent=user_agent,
        viewport={"width": 1920, "height": 1080},
        locale="en-US",
        timezone_id="America/New_York",
    )

    cookies = session_data.get("cookies", [])
    if cookies:
        await context.add_cookies(cookies)

    await Stealth().apply_stealth_async(context)
    return context


async def new_page(session_data: Optional[Dict[str, Any]] = None) -> Page:
    """Create a new page in a fresh stealth context."""
    context = await new_context(session_data)
    page = await context.new_page()

    # Apply stealth helpers.
    await _apply_stealth(page)
    return page


async def _apply_stealth(page: Page) -> None:
    """Combine playwright-stealth with CDP-level overrides."""
    await Stealth().apply_stealth_async(page)

    try:
        cdp = await page.context().new_cdp_session(page)
        await cdp.send("Page.addScriptToEvaluateOnNewDocument", {
            "source": """
                Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
                Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en'] });
                Object.defineProperty(window, 'chrome', { get: () => ({ runtime: {} }) });
                Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
                Object.defineProperty(navigator, 'deviceMemory', { get: () => 8 });
                Object.defineProperty(navigator, 'hardwareConcurrency', { get: () => 8 });
                // Remove webdriver flag from permissions if present
                const originalQuery = window.navigator.permissions.query;
                window.navigator.permissions.query = (parameters) => (
                    parameters.name === 'notifications' || parameters.name === 'midi' || parameters.name === 'clipboard-read'
                        ? Promise.resolve({ state: Notification.permission, onchange: null })
                        : originalQuery(parameters)
                );
            """
        })
        await cdp.send("Network.setExtraHTTPHeaders", {
            "headers": {
                "sec-ch-ua": '"Chromium";v="124", "Google Chrome";v="124", "Not-A.Brand";v="99"',
                "sec-ch-ua-mobile": "?0",
                "sec-ch-ua-platform": '"Windows"',
            }
        })
    except Exception as e:
        if settings.debug:
            print(f"[BrowserManager] CDP override failed: {e}")


async def close_context(context: Optional[BrowserContext]) -> None:
    """Close a context if it is still open."""
    if context is None:
        return
    try:
        await context.close()
    except Exception:
        pass


async def shutdown() -> None:
    """Gracefully close the shared browser and stop Playwright."""
    global _browser, _pw
    if _browser is not None and not _browser.is_closed():
        await _browser.close()
        _browser = None
    if _pw is not None:
        await _pw.stop()
        _pw = None
