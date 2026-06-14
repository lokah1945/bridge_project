"""Qwen provider — drives chat.qwen.ai temporary chat.

Selector strategy (verified live):

  - Model selector is a SPAN.ant-dropdown-trigger whose descendant has
    class containing "model-selector-text".  Avoid user-menu (which shares
    the same trigger class) by filtering on the inner class name.
  - The dropdown is rendered as ``.ant-dropdown:not(.ant-dropdown-hidden)``
    and contains ``Model``, ``Model Comparison`` header, then a short list of
    PRIMARY models followed by a "Expand more models" link.
  - Clicking "Expand more models" appends a much larger list of additional
    models.  Both lists should be merged for full coverage.

Submit strategy: textarea is ``[placeholder*="How can I help you today?"]``;
submit by clicking the "Send" button (aria-label="Send message") or pressing
Enter after focus.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, List

from .base import BaseProvider
from registry import ProviderRegistry

logger = logging.getLogger("bridge.qwen")


OPEN_MODEL_DROPDOWN = """() => {
    const triggers = Array.from(document.querySelectorAll('span.ant-dropdown-trigger'));
    for (const t of triggers) {
        if (t.offsetParent !== null && t.querySelector('[class*="model-selector-text"]')) {
            const r = t.getBoundingClientRect();
            ['pointerdown','mousedown','pointerup','mouseup','click'].forEach(ev =>
                t.dispatchEvent(new MouseEvent(ev, {bubbles:true, cancelable:true, view:window, button:0, clientX:r.x+5, clientY:r.y+5})));
            return 'opened';
        }
    }
    return 'no-trigger';
}"""

CLICK_EXPAND = """() => {
    const dd = document.querySelector('.ant-dropdown:not(.ant-dropdown-hidden)');
    if (!dd) return 'no-dd';
    // Find the view-more DIV with class containing 'view-more-text'
    const targets = dd.querySelectorAll('[class*="view-more-text"]');
    for (const el of targets) {
        if (el.offsetParent !== null) {
            el.click();
            return 'clicked';
        }
    }
    // fallback: any leaf element with text starting with Expand
    for (const el of dd.querySelectorAll('*')) {
        const t = (el.innerText || '').trim();
        if (/^expand more/i.test(t) && el.children.length === 0 && el.offsetParent !== null) {
            el.click();
            return 'clicked-fallback';
        }
    }
    return 'not-found';
}"""

SCRAPE_DROPDOWN_MODELS = """() => {
    const dd = document.querySelector('.ant-dropdown:not(.ant-dropdown-hidden)');
    if (!dd) return [];
    const out = new Set();
    // Model names are <span> elements with no class.  Match by text.
    // Real model names contain a dash or digit (e.g. "Qwen3.7-Plus", "Qwen3-Max").
    for (const el of dd.querySelectorAll('span, div')) {
        if (el.children.length !== 0) continue;
        if (!el.offsetParent) continue;
        const t = (el.innerText || '').trim();
        if (!t || t.length > 60) continue;
        if (!/^Qwen/i.test(t)) continue;
        if (/Expand|Comparison|series|natively|flagship|capable|highly/i.test(t)) continue;
        // Require at least one digit, dash, dot, or "Plus/Max/Flash/Coder/Omni/VL"
        if (!/[-]/.test(t) && !/[0-9]/.test(t) && !/(Plus|Max|Flash|Coder|Omni|VL|Turbo)/.test(t)) continue;
        out.add(t);
    }
    return Array.from(out);
}"""


@ProviderRegistry.register("qwen")
class QwenProvider(BaseProvider):
    name = "qwen"

    URL = "https://chat.qwen.ai/?temporary-chat=true"

    async def list_models(self, **kwargs) -> List[str]:
        page = await self.setup_browser()
        try:
            await page.goto(self.URL, wait_until="domcontentloaded", timeout=60000)
            try:
                await page.wait_for_function(
                    "() => document.querySelector('textarea')",
                    timeout=90000,
                )
            except Exception as exc:
                logger.warning("qwen: textarea wait failed: %s", exc)
                return []
            await asyncio.sleep(3)

            await page.evaluate(OPEN_MODEL_DROPDOWN)
            await asyncio.sleep(1.5)

            primary = await page.evaluate(SCRAPE_DROPDOWN_MODELS)
            logger.info("qwen primary models: %d (%s)", len(primary), primary)

            # Use Playwright native click for the Expand link (JS .click() does
            # not trigger React's onClick reliably for this component).
            try:
                await page.locator('text=Expand more models').first.click(timeout=5000)
            except Exception as exc:
                logger.debug("qwen expand native click failed: %s", exc)
                # fallback: JS click on the view-more-text DIV
                await page.evaluate(CLICK_EXPAND)
            await asyncio.sleep(2)

            expanded = await page.evaluate(SCRAPE_DROPDOWN_MODELS)
            logger.info(
                "qwen expanded models: %d (added %d)",
                len(expanded),
                len(expanded) - len(primary),
            )

            await page.keyboard.press("Escape")
            await asyncio.sleep(0.3)

            return sorted(set(primary) | set(expanded))
        finally:
            try:
                await self.clear_context_cookies()
            except Exception:
                pass

    async def execute(self, model_id: str, prompt: str, params: Dict[str, Any]) -> str:
        page = await self.setup_browser()
        try:
            await page.goto(self.URL, wait_until="domcontentloaded", timeout=60000)
            try:
                await page.wait_for_function(
                    "() => document.querySelector('textarea')",
                    timeout=90000,
                )
            except Exception as exc:
                logger.warning("qwen execute: textarea wait failed: %s", exc)
            await asyncio.sleep(3)
            if not await self._select_model(page, model_id):
                return f"(model {model_id!r} not found in Qwen dropdown)"
            await self._apply_options(page, params)
            await self._send_prompt(page, prompt)
            # wait for assistant content
            await asyncio.sleep(2)
            for _ in range(60):
                text = await self._read_latest_message(page)
                if text and text.strip() and "How can I help" not in text:
                    return text.strip()
                await asyncio.sleep(2)
            return "(no response)"
        finally:
            try:
                await self.clear_context_cookies()
            except Exception:
                pass

    async def _select_model(self, page, model_id: str) -> bool:
        """Open the model dropdown and click ``model_id``.  Returns True if clicked."""
        # First, ensure no dropdown is open.
        try:
            await page.keyboard.press("Escape")
            await asyncio.sleep(0.4)
        except Exception:
            pass

        # Try up to 3 times: open dropdown → find → click → verify selected.
        for attempt in range(3):
            await page.evaluate(OPEN_MODEL_DROPDOWN)
            await asyncio.sleep(1.2)
            clicked = await page.evaluate(
                """(modelId) => {
                    const dd = document.querySelector('.ant-dropdown:not(.ant-dropdown-hidden)');
                    if (!dd) return 'no-dd';
                    for (const el of dd.querySelectorAll('span, div')) {
                        if (el.children.length !== 0) continue;
                        const t = (el.innerText || '').trim();
                        if (t === modelId) {
                            el.click();
                            return 'clicked';
                        }
                    }
                    return 'not-found';
                }""",
                model_id,
            )
            if clicked == 'clicked':
                await asyncio.sleep(0.6)
                return True
            if clicked == 'not-found':
                # Need to expand first.
                try:
                    await page.locator('text=Expand more models').first.click(timeout=5000)
                    await asyncio.sleep(1.5)
                except Exception as exc:
                    logger.debug("qwen expand click failed: %s", exc)
                    await page.evaluate(CLICK_EXPAND)
                    await asyncio.sleep(1.5)
                # re-check after expand
                clicked2 = await page.evaluate(
                    """(modelId) => {
                        const dd = document.querySelector('.ant-dropdown:not(.ant-dropdown-hidden)');
                        if (!dd) return 'no-dd';
                        for (const el of dd.querySelectorAll('span, div')) {
                            if (el.children.length !== 0) continue;
                            const t = (el.innerText || '').trim();
                            if (t === modelId) {
                                el.click();
                                return 'clicked';
                            }
                        }
                        return 'not-found';
                    }""",
                    model_id,
                )
                if clicked2 == 'clicked':
                    await asyncio.sleep(0.6)
                    return True
                # Last attempt: take a debug snapshot of the available options.
                available = await page.evaluate(
                    """() => Array.from(document.querySelectorAll(
                        '.ant-dropdown:not(.ant-dropdown-hidden) span, .ant-dropdown:not(.ant-dropdown-hidden) div'
                    )).filter(el => el.children.length === 0 && el.innerText && el.innerText.trim().length > 0 && el.innerText.trim().length < 60)
                      .map(el => el.innerText.trim())
                      .filter(t => /^Qwen/i.test(t))
                      .slice(0, 30)"""
                )
                logger.warning(
                    "qwen: model %r not found in dropdown (attempt %d); "
                    "available (first 30): %s",
                    model_id, attempt + 1, available,
                )
                # close dropdown before next attempt
                try:
                    await page.keyboard.press("Escape")
                    await asyncio.sleep(0.5)
                except Exception:
                    pass
            else:  # 'no-dd'
                logger.debug("qwen: dropdown not visible on attempt %d", attempt + 1)
                await asyncio.sleep(1.0)
        logger.error("qwen: gave up selecting %r after 3 attempts", model_id)
        return False

        # Try again after expand.
        clicked2 = await page.evaluate(
            """(modelId) => {
                const dd = document.querySelector('.ant-dropdown:not(.ant-dropdown-hidden)');
                if (!dd) return 'no-dd';
                for (const el of dd.querySelectorAll('span, div')) {
                    if (el.children.length !== 0) continue;
                    const t = (el.innerText || '').trim();
                    if (t === modelId) {
                        el.click();
                        return 'clicked';
                    }
                }
                // log available models for debugging
                const all = [];
                for (const el of dd.querySelectorAll('span, div')) {
                    if (el.children.length !== 0) continue;
                    const t = (el.innerText || '').trim();
                    if (t && /^Qwen/i.test(t) && t.length < 80) all.push(t);
                }
                return JSON.stringify({available: all.slice(0, 30)});
            }""",
            model_id,
        )
        if clicked2 == 'clicked':
            await asyncio.sleep(0.6)
            return
        logger.warning("qwen: model %r not found in dropdown; %s", model_id, clicked2)

    async def _apply_options(self, page, params: Dict[str, Any]) -> None:
        # thinking mode toggle
        thinking = params.get("thinking", "auto")
        if thinking != "auto":
            try:
                loc = page.locator('[class*="thinking-mode"], [class*="thinking-toggle"]').first
                if await loc.count() > 0:
                    await loc.click(timeout=2000)
                    await asyncio.sleep(0.3)
                    await page.locator(f'text="{thinking}"').first.click(timeout=2000)
            except Exception as exc:
                logger.debug("qwen thinking toggle failed: %s", exc)
        # tools toggle
        if params.get("tools") is False:
            try:
                loc = page.locator('[class*="tool-toggle"], button[aria-label*="tool" i]').first
                if await loc.count() > 0:
                    await loc.click(timeout=2000)
            except Exception as exc:
                logger.debug("qwen tool toggle failed: %s", exc)

    async def _send_prompt(self, page, prompt: str) -> None:
        ta = page.locator('textarea').first
        await ta.click()
        await asyncio.sleep(0.3)
        # Use React-friendly value setter + dispatch input event
        await page.evaluate(
            """(text) => {
                const ta = document.querySelector('textarea');
                const setter = Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, 'value').set;
                setter.call(ta, text);
                ta.dispatchEvent(new Event('input', { bubbles: true }));
                ta.focus();
            }""",
            prompt,
        )
        await asyncio.sleep(0.5)
        # try Enter first
        await page.keyboard.press("Enter")
        await asyncio.sleep(1)
        # if textarea still has value, try clicking Send button
        if await ta.input_value() == prompt:
            try:
                await page.locator('button[aria-label*="Send" i]').first.click(timeout=3000)
            except Exception:
                pass

    async def _read_latest_message(self, page) -> str:
        return await page.evaluate(
            """() => {
                // Qwen assistant response has class 'qwen-markdown' or 'response-message-content'.
                // Pick the LAST matching element (most recent assistant turn).
                const sels = ['[class*="qwen-markdown-paragraph"]', '[class*="qwen-markdown-loose"]', '[class*="custom-qwen-markdown"]', '[class*="response-message-content"]'];
                for (const sel of sels) {
                    const els = Array.from(document.querySelectorAll(sel));
                    if (els.length) {
                        return (els[els.length - 1].innerText || '').trim();
                    }
                }
                return '';
            }"""
        )
