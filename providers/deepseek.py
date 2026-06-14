"""DeepSeek provider — drives chat.deepseek.com.

Selector strategy:

  - Login state check: chat.deepseek.com redirects to ``/sign_in`` when the
    session cookies are stale.  We detect this via ``page.url`` and bail
    out early with a clear error message.

  - Model selector is the model switcher button (text contains the
    current model name, e.g. "DeepSeek-V3").  Click opens a dropdown
    listing the available models.

  - Submit: the chat textarea submits on Enter.  The ``.ds-message``
    selector waits for the assistant response to appear.

Limitations:

  - When DeepSeek cookies are stale, ``/v1/chat/completions`` returns
    a clear error message instead of hanging on a 30 s ``fill()``
    timeout.  This is a graceful failure mode (HTTP 200 with a
    descriptive ``content`` field).
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, List

from .base import BaseProvider
from registry import ProviderRegistry

logger = logging.getLogger("bridge.deepseek")


@ProviderRegistry.register("deepseek")
class DeepSeekProvider(BaseProvider):
    """Drives chat.deepseek.com."""

    name = "deepseek"

    URL = "https://chat.deepseek.com/"

    FALLBACK_MODELS = ["deepseek-chat", "deepseek-reasoner", "deepseek-coder"]

    async def list_models(self, **kwargs) -> List[str]:
        if not self.cookies:
            logger.warning("deepseek: no session cookies — returning []")
            return []
        page = await self.setup_browser()
        try:
            await page.goto(self.URL, wait_until="domcontentloaded", timeout=60000)
            await asyncio.sleep(8.0)
            # Detect login redirect.  DeepSeek returns /sign_in when not authed.
            url = page.url
            if "/sign_in" in url:
                logger.warning(
                    "deepseek: redirected to /sign_in — cookies are STALE; "
                    "user needs to re-login via bridge-server. Returning FALLBACK."
                )
                return list(self.FALLBACK_MODELS)
            models = await self._scrape_options(page)
            if not models:
                logger.warning("deepseek returned no models — using FALLBACK list")
                return list(self.FALLBACK_MODELS)
            return sorted(set(models))
        finally:
            try:
                await self.cleanup()
            except Exception:
                pass

    async def _scrape_options(self, page) -> List[str]:
        for trig in [
            'button:has-text("Model")',
            '[role="combobox"]',
            '.model-selector',
        ]:
            try:
                loc = page.locator(trig).first
                if await loc.count() == 0:
                    continue
                await loc.click(timeout=2500)
                await asyncio.sleep(0.6)
                opts = await page.evaluate(
                    """() => {
                        const sels = ['[role="option"]', '.model-option', '.dropdown-item', 'li'];
                        const out = new Set();
                        for (const s of sels) {
                            for (const el of document.querySelectorAll(s)) {
                                const t = (el.innerText || '').trim();
                                if (t && t.length < 80) out.add(t.split('\\n', 1)[0].trim());
                            }
                        }
                        return Array.from(out);
                    }"""
                )
                if opts:
                    return [o for o in opts if o and len(o) < 80]
            except Exception as exc:
                logger.debug("deepseek trigger %s failed: %s", trig, exc)
        return []

    async def execute(self, model_id: str, prompt: str, params: Dict[str, Any]) -> str:
        if not self.cookies:
            return self._auth_error_msg()
        page = await self.setup_browser()
        try:
            await page.goto(self.URL, wait_until="domcontentloaded", timeout=60000)
            await asyncio.sleep(3.0)
            # Fast-fail if we land on /sign_in or userToken is null.
            auth_state = await page.evaluate(
                """() => ({
                    url: location.href,
                    hasSignIn: location.pathname.includes('sign_in'),
                    userToken: (() => {
                        try {
                            const t = localStorage.getItem('userToken');
                            if (!t) return null;
                            const parsed = JSON.parse(t);
                            return parsed?.value || null;
                        } catch (e) { return null; }
                    })(),
                })"""
            )
            if auth_state["hasSignIn"] or not auth_state["userToken"]:
                return self._auth_error_msg()
            await self._apply_options(page, params)
            await self._select_model(page, model_id)
            ta = page.locator("textarea").first
            if await ta.count() == 0:
                return "(deepseek chat textarea not present)"
            try:
                await ta.fill(prompt, timeout=10000)
            except Exception:
                return "(deepseek chat textarea fill timed out)"
            await page.keyboard.press("Enter")
            for _ in range(22):  # ~45 s max — under 1 minute per spec
                text = await page.evaluate(
                    """() => {
                        const sels = ['.ds-message', '[class*="message"]', '[class*="response"]'];
                        for (const s of sels) {
                            const els = Array.from(document.querySelectorAll(s));
                            if (els.length) {
                                return (els[els.length-1].innerText || els[els.length-1].textContent || '').trim();
                            }
                        }
                        return '';
                    }"""
                )
                if text and text.strip():
                    return text.strip()
                await asyncio.sleep(2)
            return "(no response from deepseek within 45s)"
        finally:
            try:
                await self.cleanup()
            except Exception:
                pass

    @staticmethod
    def _auth_error_msg() -> str:
        return (
            "(deepseek not logged in: chat.deepseek.com requires an active "
            "user session.  The cookies cached by bridge-server are stale "
            "(localStorage userToken is null).  "
            "FIX: open https://chat.deepseek.com/ in bridge-server's headfull "
            "Chrome, log in (Google/email/Apple), wait for the chat textarea "
            "to appear, then re-run /v1/chat/completions.  "
            "Set BRIDGE_SERVER_URL to point to bridge-server and refresh.)"
        )

    async def _select_model(self, page, model_id: str) -> None:
        for trig in [
            'button:has-text("Model")',
            '[role="combobox"]',
            '.model-selector',
        ]:
            try:
                loc = page.locator(trig).first
                if await loc.count() == 0:
                    continue
                await loc.click(timeout=2500)
                await asyncio.sleep(0.4)
                opt = page.locator(f'[role="option"]:has-text("{model_id}")').first
                if await opt.count() > 0:
                    await opt.click(timeout=2500)
                    return
            except Exception as exc:
                logger.debug("deepseek select %s failed: %s", trig, exc)

    async def _apply_options(self, page, params: Dict[str, Any]) -> None:
        mode = params.get("mode", "fast")
        if mode == "expert":
            try:
                loc = page.locator('.mode-expert-toggle, [data-testid*="expert" i]').first
                if await loc.count() > 0:
                    await loc.click(timeout=2000)
            except Exception as exc:
                logger.debug("expert toggle failed: %s", exc)
        if params.get("thinking") is True:
            try:
                loc = page.locator('.think-toggle, [data-testid*="think" i]').first
                if await loc.count() > 0:
                    await loc.click(timeout=2000)
            except Exception as exc:
                logger.debug("think toggle failed: %s", exc)
        if params.get("search") is True:
            try:
                loc = page.locator('.search-toggle, [data-testid*="search" i]').first
                if await loc.count() > 0:
                    await loc.click(timeout=2000)
            except Exception as exc:
                logger.debug("search toggle failed: %s", exc)
