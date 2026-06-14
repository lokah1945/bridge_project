"""Arena.ai provider — drives arena.ai with 4 modality URLs.

Selector strategy (verified against live DOM, see ``probe_arena_force.py``):

  - The mode switcher is a button ``role=combobox`` with text like ``Direct``,
    ``Battle``, ``Side-by-Side``, ``Agent``.
  - The MODEL selector is a *separate* button with ``aria-haspopup="dialog"``,
    showing the current model name (e.g. ``Max``).
  - When clicked, it opens a Radix UI dialog containing ``[role="option"]``
    elements whose ``innerText`` is the model name (possibly followed by a
    short description, separated by newlines).

Operational notes discovered during end-to-end testing:

  - The site displays a Cloudflare JS challenge on cold navigations; can take
    up to 120 s before the React app boots.  We wait for app readiness via a
    JS predicate (button present OR body no longer mentions security check).
  - After load, a Terms-of-Use modal appears with an ``Agree`` button which
    must be clicked before the chat input becomes interactive.
  - ``setup_browser`` reuses the same Playwright page across calls so the
    Cloudflare challenge only has to be passed once per provider instance.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, List

from .base import BaseProvider
from registry import ProviderRegistry

logger = logging.getLogger("bridge.arena")


# ---------- JS fragments ---------------------------------------------------

WAIT_FOR_APP_READY = """() => {
    if (document.querySelector('button[aria-haspopup="dialog"]')) return true;
    const t = (document.body && document.body.innerText) || '';
    if (!/security verification|performing security|just a moment|verify you are human/i.test(t) && t.length > 100) return true;
    return false;
}"""

DISMISS_TERMS = """() => {
    // Try multiple strategies to dismiss the Terms-of-Use modal:
    //  1. Click a button whose visible text is exactly "Agree" or "I agree".
    //  2. Click the corresponding keyboard hint (Enter on the document).
    //  3. Click any button whose text contains "Agree".
    const btns = Array.from(document.querySelectorAll('button'));
    for (const b of btns) {
        const t = (b.innerText || b.textContent || '').trim();
        if (/^(agree|i agree)$/i.test(t)) { b.click(); return 'clicked-' + t; }
    }
    // Last resort: dispatch an Enter key on document (the page hints at it).
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }));
    document.dispatchEvent(new KeyboardEvent('keypress', { key: 'Enter', bubbles: true }));
    return 'sent-enter';
}"""

CLICK_MODEL_TRIGGER = """() => {
    const btns = Array.from(document.querySelectorAll('button[aria-haspopup="dialog"]'));
    if (!btns.length) return null;
    let target = btns.find(b => b.offsetParent !== null);
    if (!target) target = btns.find(b => { const r = b.getBoundingClientRect(); return r.width > 0 && r.height > 0; });
    if (!target) target = btns[0];
    const ctl = target.getAttribute('aria-controls');
    try { target.click(); } catch(e) {}
    return ctl;
}"""

WAIT_FOR_OPTIONS = """() => document.querySelectorAll('[role="option"]').length > 5"""

CLICK_OPTION_BY_NAME = """(modelId) => {
    const opts = Array.from(document.querySelectorAll('[role="option"]'));
    const target = opts.find(o => {
        const t = (o.innerText || o.textContent || '').trim();
        return t.split('\\n', 1)[0].trim().toLowerCase() === modelId.toLowerCase();
    });
    if (target) { target.click(); return true; }
    return false;
}"""

SCRAPE_OPTIONS = """() => Array.from(document.querySelectorAll('[role="option"]'))
                    .map(o => (o.innerText || o.textContent || '').trim())
                    .filter(Boolean)"""

WAIT_FOR_RESPONSE = """() => {
    const sels = ['[data-message-author="assistant"]',
                  '.assistant-message',
                  '[class*="response"]',
                  '[class*="assistant"]'];
    for (const s of sels) {
        if (document.querySelectorAll(s).length > 0) return true;
    }
    return false;
}"""

EXTRACT_LAST_RESPONSE = """() => {
    const sels = ['[data-message-author="assistant"]',
                  '.assistant-message',
                  '[class*="response"]',
                  '[class*="assistant"]'];
    for (const s of sels) {
        const els = Array.from(document.querySelectorAll(s));
        if (els.length) {
            const last = els[els.length-1];
            return (last.innerText || last.textContent || '').trim();
        }
    }
    return '';
}"""


@ProviderRegistry.register("arena")
class ArenaProvider(BaseProvider):
    name = "arena"

    MODALITIES = {
        "text": "https://arena.ai/text/direct",
        "search": "https://arena.ai/search/direct",
        "image": "https://arena.ai/image/direct",
        "code": "https://arena.ai/code/direct",
    }

    # ------------------------------------------------------------------ discovery

    async def list_models(self, modality: str = "text", **kwargs) -> List[str]:
        if modality not in self.MODALITIES:
            raise ValueError(f"unknown modality: {modality}")
        url = self.MODALITIES[modality]

        page = await self.setup_browser()
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=60000)
            try:
                await page.wait_for_function(WAIT_FOR_APP_READY, timeout=120000)
            except Exception as exc:
                logger.warning("arena(%s): app readiness wait failed: %s", modality, exc)
                return []
            await page.evaluate(DISMISS_TERMS)
            await asyncio.sleep(1.5)
            ctl = await page.evaluate(CLICK_MODEL_TRIGGER)
            if not ctl:
                logger.warning("arena(%s): no model-trigger button", modality)
                return []
            try:
                await page.wait_for_function(WAIT_FOR_OPTIONS, timeout=10000)
            except Exception:
                pass
            await asyncio.sleep(0.4)
            opts = await page.evaluate(SCRAPE_OPTIONS)
            # close dropdown to leave page clean
            await page.keyboard.press("Escape")
            await asyncio.sleep(0.2)

            models: List[str] = []
            for raw in opts or []:
                first = raw.split("\n", 1)[0].strip()
                if first and len(first) < 100:
                    models.append(first)
            filtered = [
                m for m in models
                if (("-" in m) or ("." in m) or any(c.isdigit() for c in m))
                and m.lower() not in {"max", "auto", "default"}
            ]
            seen = set()
            deduped = []
            for m in filtered:
                if m not in seen:
                    seen.add(m)
                    deduped.append(m)
            logger.info(
                "arena(%s): %d raw options, %d after filter",
                modality,
                len(opts or []),
                len(deduped),
            )
            return deduped
        finally:
            try:
                await self.clear_context_cookies()
            except Exception:
                pass

    # ------------------------------------------------------------------ execute

    async def execute(self, model_id: str, prompt: str, params: Dict[str, Any]) -> str:
        modality = params.get("modality", "text")
        if modality not in self.MODALITIES:
            raise ValueError(f"unknown modality: {modality}")
        url = self.MODALITIES[modality]

        page = await self.setup_browser()
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=60000)
            try:
                await page.wait_for_function(WAIT_FOR_APP_READY, timeout=120000)
            except Exception as exc:
                logger.warning("arena(%s) execute wait failed: %s", modality, exc)
            await page.evaluate(DISMISS_TERMS)
            await asyncio.sleep(1.5)
            await self._select_model(page, model_id)
            # Use the textarea whose placeholder is "Ask anything…" (the chat input).
            try:
                await page.locator('textarea[placeholder*="Ask anything" i]').first.fill(prompt)
            except Exception:
                # fall back to last visible textarea
                await page.evaluate(
                    """(p) => {
                        const tas = Array.from(document.querySelectorAll('textarea'));
                        const v = tas.find(t => t.offsetParent !== null && t.placeholder && t.placeholder.toLowerCase().includes('ask'));
                        if (v) {
                            v.focus();
                            const setter = Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, 'value').set;
                            setter.call(v, p);
                            v.dispatchEvent(new Event('input', { bubbles: true }));
                            v.dispatchEvent(new Event('change', { bubbles: true }));
                        }
                    }""",
                    prompt,
                )
            await page.keyboard.press("Enter")
            try:
                await page.wait_for_function(WAIT_FOR_RESPONSE, timeout=120000)
            except Exception as exc:
                logger.warning("arena(%s) response wait timed out: %s", modality, exc)
            await asyncio.sleep(2.5)
            text = await page.evaluate(EXTRACT_LAST_RESPONSE)
            return text or "(empty response)"
        finally:
            try:
                await self.clear_context_cookies()
            except Exception:
                pass

    async def _select_model(self, page, model_id: str) -> None:
        try:
            await page.keyboard.press("Escape")
            await asyncio.sleep(0.3)
        except Exception:
            pass
        ctl = await page.evaluate(CLICK_MODEL_TRIGGER)
        if not ctl:
            raise RuntimeError("model trigger button not found")
        try:
            await page.wait_for_function(WAIT_FOR_OPTIONS, timeout=10000)
        except Exception:
            pass
        await asyncio.sleep(0.4)
        clicked = await page.evaluate(CLICK_OPTION_BY_NAME, model_id)
        if not clicked:
            opts_now = await page.evaluate(
                "() => Array.from(document.querySelectorAll('[role=\"option\"]'))"
                ".map(o => (o.innerText||'').split('\\n')[0].trim()).slice(0,20)"
            )
            raise RuntimeError(
                f"model option {model_id!r} not found; available (first 20): {opts_now}"
            )
        await asyncio.sleep(0.6)
