"""DeepSeek provider — implementation per MASTER PROMPT Bagian 11."""

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
            await asyncio.sleep(5.0)
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
                        const sels = ['[role=\"option\"]', '.model-option', '.dropdown-item', 'li'];
                        const out = new Set();
                        for (const s of sels) {
                            for (const el of document.querySelectorAll(s)) {
                                const t = (el.innerText || el.textContent || '').trim();
                                if (t && t.length < 80) out.add(t);
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
        page = await self.setup_browser()
        try:
            await page.goto(self.URL, wait_until="networkidle", timeout=60000)
            await asyncio.sleep(1.5)
            await self._apply_options(page, params)
            await self._select_model(page, model_id)
            await page.fill("textarea", prompt)
            await page.keyboard.press("Enter")
            await page.wait_for_selector(
                ".ds-message, [class*=\"message\"]",
                timeout=60000,
            )
            await asyncio.sleep(2.0)
            text = await page.evaluate(
                """() => {
                    const sels = ['.ds-message', '[class*=\"message\"]', '[class*=\"response\"]'];
                    for (const s of sels) {
                        const els = Array.from(document.querySelectorAll(s));
                        if (els.length) return (els[els.length-1].innerText || els[els.length-1].textContent || '').trim();
                    }
                    return '';
                }"""
            )
            return text or "(empty response)"
        finally:
            try:
                await self.clear_context_cookies()
            except Exception:
                pass

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
                loc = page.locator(".mode-expert-toggle, [data-testid*=\"expert\" i]").first
                if await loc.count() > 0:
                    await loc.click(timeout=2000)
            except Exception as exc:
                logger.debug("expert toggle failed: %s", exc)
        if params.get("thinking") is True:
            try:
                loc = page.locator(".think-toggle, [data-testid*=\"think\" i]").first
                if await loc.count() > 0:
                    await loc.click(timeout=2000)
            except Exception as exc:
                logger.debug("think toggle failed: %s", exc)
        if params.get("search") is True:
            try:
                loc = page.locator(".search-toggle, [data-testid*=\"search\" i]").first
                if await loc.count() > 0:
                    await loc.click(timeout=2000)
            except Exception as exc:
                logger.debug("search toggle failed: %s", exc)
