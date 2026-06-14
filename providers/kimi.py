"""Kimi provider — drives www.kimi.com (Moonshot AI's chat UI).

Selector strategy (verified against live DOM, see ``probe_kimi3.py``):

  - The current model name is rendered in a ``<span class="name">`` inside a
    ``<div class="current-model">``.  Clicking that container opens a Vue-
    based popup (``<div class="v-binder-follower-content">``) listing
    every available model — there is NO "Expand More" trick; the 4 Kimi
    models fit in one popup.
  - Kimi cookies are served by bridge-server under the ``arena`` profile
    (the same browser profile that logs into Arena.ai also keeps the
    ``.kimi.com`` cookies).  ``ProviderRegistry`` automatically passes
    the arena session to this provider via
    ``client.py::get_effective_session``.
  - We currently use ``?temporary-chat=true`` style behaviour by simply
    NOT logging in: kimi's chat-history sync is disabled when no user
    is logged in, which matches our zero-footprint requirement.

Submit strategy: textarea placeholder is ``Ask Anything...``; submit by
pressing Enter (the form sends on Enter just like a normal <textarea>).
"""

from __future__ import annotations

import asyncio
import re
import logging
from typing import Any, Dict, List

from .base import BaseProvider
from registry import ProviderRegistry

logger = logging.getLogger("bridge.kimi")


# ---------- JS fragments ---------------------------------------------------

OPEN_MODEL_POPUP_JS = """() => {
    // Click the current-model DIV to open the popup.
    const el = document.querySelector('.current-model, .model-name');
    if (!el || !el.offsetParent) return 'no-trigger';
    const r = el.getBoundingClientRect();
    ['pointerdown','mousedown','pointerup','mouseup','click'].forEach(ev =>
        el.dispatchEvent(new MouseEvent(ev, {bubbles:true, cancelable:true, view:window, button:0, clientX:r.x+10, clientY:r.y+10})));
    return 'opened';
}"""

SCRAPE_POPUP_MODELS_JS = """() => {
    const popups = Array.from(document.querySelectorAll('.v-binder-follower-content, [class*=\"model-list\" i]')).filter(p => {
        const r = p.getBoundingClientRect();
        return r.width > 100 && r.height > 100 && p.offsetParent !== null;
    });
    if (!popups.length) return [];
    // Popup lists items as <div class="model-item">...</div>
    const items = popups[0].querySelectorAll('.model-item, [class*=\"model-item\"]');
    const out = new Set();
    for (const it of items) {
        // First child <span class="name"> holds the model id
        const name = it.querySelector('.name, [class*=\"name\"]');
        const text = (name ? name.innerText : it.innerText || '').trim();
        if (text && text.length < 60 && /^K\\d|^kimi/i.test(text)) {
            out.add(text.split('\\n', 1)[0].trim());
        }
    }
    return Array.from(out);
}"""

SELECT_MODEL_JS = """(modelId) => {
    const popups = Array.from(document.querySelectorAll('.v-binder-follower-content, [class*=\"model-list\" i]')).filter(p => {
        const r = p.getBoundingClientRect();
        return r.width > 100 && r.height > 100 && p.offsetParent !== null;
    });
    if (!popups.length) return 'no-popup';
    const items = popups[0].querySelectorAll('.model-item, [class*=\"model-item\"]');
    for (const it of items) {
        const name = it.querySelector('.name, [class*=\"name\"]');
        const text = (name ? name.innerText : it.innerText || '').trim();
        if (text.split('\\n', 1)[0].trim() === modelId) {
            const r = it.getBoundingClientRect();
            ['pointerdown','mousedown','pointerup','mouseup','click'].forEach(ev =>
                it.dispatchEvent(new MouseEvent(ev, {bubbles:true, cancelable:true, view:window, button:0, clientX:r.x+10, clientY:r.y+10})));
            return 'clicked';
        }
    }
    return 'not-found';
}"""


@ProviderRegistry.register("kimi")
class KimiProvider(BaseProvider):
    name = "kimi"

    URL = "https://www.kimi.com/"

    async def list_models(self, **kwargs) -> List[str]:
        page = await self.setup_browser()
        try:
            await page.goto(self.URL, wait_until="domcontentloaded", timeout=60000)
            try:
                await page.wait_for_function(
                    "() => document.querySelector('.current-model') || document.querySelector('textarea')",
                    timeout=90000,
                )
            except Exception as exc:
                logger.warning("kimi: page readiness wait failed: %s", exc)
                return []
            await asyncio.sleep(5)
            await page.evaluate(OPEN_MODEL_POPUP_JS)
            await asyncio.sleep(1.5)
            models = await page.evaluate(SCRAPE_POPUP_MODELS_JS)
            logger.info("kimi models: %d (%s)", len(models), models)
            # close popup
            try:
                await page.keyboard.press("Escape")
            except Exception:
                pass
            return sorted(set(models))
        finally:
            try:
                await self.clear_context_cookies()
            except Exception:
                pass

    async def execute(self, model_id: str, prompt: str, params: Dict[str, Any]) -> str:
        if not self.cookies:
            return "(no session for kimi - login required on bridge-server)"
        page = await self.setup_browser()
        try:
            await page.goto(self.URL, wait_until="domcontentloaded", timeout=60000)
            try:
                await page.wait_for_function(
                    "() => document.querySelector('.chat-input-editor, [contenteditable=\"true\"]')",
                    timeout=60000,
                )
            except Exception as exc:
                logger.warning("kimi execute: page readiness wait failed: %s", exc)
                return "(no chat editor on kimi.com - page may require login)"
            await asyncio.sleep(3)

            # Detect login state.  Kimi shows "Log in to sync chat history"
            # when the user has no session.  Chat submission silently opens
            # a full login modal (Google/phone).  Verify before trying.
            login_state = await page.evaluate(
                """() => {
                    const t = document.body.innerText || '';
                    return {
                        hasSyncBanner: /log in to sync|sign in to sync/i.test(t),
                        hasAvatar: !!document.querySelector('[class*="avatar" i]'),
                        hasKimiAuth: !!document.cookie.match(/kimi-auth/),
                    };
                }"""
            )
            if not login_state["hasAvatar"] or not login_state["hasKimiAuth"]:
                # We can still try to send, but it will open a login modal.
                logger.warning(
                    "kimi: detected 'log in to sync' banner and no avatar/auth cookie; "
                    "chat will require manual login"
                )

            if not await self._select_model(page, model_id):
                logger.warning("kimi: model selection failed; continuing anyway")

            sent_ok = await self._send_prompt(page, prompt)
            if not sent_ok:
                return "(failed to fill Kimi editor)"

            # Wait up to 60s for response OR login modal to appear.
            for _ in range(30):
                text = await self._read_latest_message(page)
                # Detect: clicking Send opened a login modal (chat requires
                # Kimi account login, separate from session cookies).
                login_modal = await page.evaluate(
                    """() => {
                        const t = document.body.innerText || '';
                        return /log in to[\\s\\S]*chat with kimi|continue with google|log in with phone/i.test(t);
                    }"""
                )
                if login_modal:
                    return (
                    "(kimi not logged in: chat requires Google/phone login which "
                    "can't be automated.  FIX: open https://www.kimi.com/ in "
                    "bridge-server's headfull Chrome, sign in with Google or "
                    "phone, wait for chat input to become active, then re-run.  "
                    "Session cookies alone are not enough — Kimi uses a "
                    "separate login state for billing/quota tracking.)"
                )
                if text and text.strip() and "Ask Anything" not in text:
                    if re.search(r"log in to sync|sign in to sync", text, re.I):
                        return "(kimi requires login - response blocked)"
                    return text.strip()
                await asyncio.sleep(2)
            return "(no response from Kimi within 60s)"
        finally:
            try:
                await self.cleanup()
            except Exception:
                pass

    async def _select_model(self, page, model_id: str) -> bool:
        """Open the model popup, click ``model_id``, return True if clicked."""
        # Make sure no popup is open and the chat input has focus context.
        try:
            await page.keyboard.press("Escape")
            await asyncio.sleep(0.4)
        except Exception:
            pass

        for attempt in range(3):
            await page.evaluate(OPEN_MODEL_POPUP_JS)
            await asyncio.sleep(1.5)
            # Verify popup is actually visible.
            popup_visible = await page.evaluate(
                "() => { const p = document.querySelector('.v-binder-follower-content'); return p ? (p.getBoundingClientRect().width > 100 && p.offsetParent !== null) : false; }"
            )
            if not popup_visible:
                logger.debug("kimi: popup not visible on attempt %d", attempt + 1)
                await asyncio.sleep(0.8)
                continue
            # Popup is open — click the option.
            clicked = await page.evaluate(SELECT_MODEL_JS, model_id)
            if clicked == 'clicked':
                await asyncio.sleep(0.6)
                # Close popup if still open.
                try:
                    await page.keyboard.press("Escape")
                except Exception:
                    pass
                await asyncio.sleep(0.4)
                return True
            # If popup was open but model not found, log it.
            if clicked == 'not-found':
                available = await page.evaluate(
                    """() => Array.from(document.querySelectorAll(
                        '.v-binder-follower-content .model-item .name, .v-binder-follower-content [class*="name"]'
                    )).map(el => (el.innerText || '').trim()).filter(Boolean).slice(0, 10)"""
                )
                logger.warning(
                    "kimi: model %r not in popup (attempt %d); available: %s",
                    model_id, attempt + 1, available,
                )
                try:
                    await page.keyboard.press("Escape")
                except Exception:
                    pass
                await asyncio.sleep(0.6)
        logger.error("kimi: gave up selecting %r after 3 attempts", model_id)
        return False

    async def _send_prompt(self, page, prompt: str) -> bool:
        """Fill the Kimi chat editor and submit.  Returns True if editor got the text."""
        # Click on the editor to focus it (use force in case there's an overlay).
        try:
            await page.locator('.chat-input-editor').first.click(force=True, timeout=3000)
            await asyncio.sleep(0.4)
        except Exception as exc:
            logger.debug("kimi: editor click failed: %s", exc)
            return False

        # Clear any existing content (Ctrl+A then Backspace).
        await page.keyboard.press("Control+A")
        await asyncio.sleep(0.2)
        await page.keyboard.press("Backspace")
        await asyncio.sleep(0.3)

        # Type character-by-character.  Kimi's editor is a Lexical/ProseMirror-style
        # rich text editor that needs real keyboard events to register input.
        try:
            await page.keyboard.type(prompt, delay=50)
        except Exception as exc:
            logger.warning("kimi: keyboard.type failed (%s), trying innerText fallback", exc)
            await page.evaluate(
                """(text) => {
                    const el = document.querySelector('.chat-input-editor');
                    if (!el) return false;
                    el.focus();
                    // Replace the text via execCommand (still works in most editors).
                    const sel = window.getSelection();
                    if (sel) {
                        const range = document.createRange();
                        range.selectNodeContents(el);
                        sel.removeAllRanges();
                        sel.addRange(range);
                        document.execCommand('insertText', false, text);
                    } else {
                        el.innerText = text;
                    }
                    el.dispatchEvent(new InputEvent('input', { bubbles: true, data: text }));
                    return el.innerText.trim().length > 0;
                }""",
                prompt,
            )
            await asyncio.sleep(0.5)

        await asyncio.sleep(0.5)
        # Verify the editor received the text.
        got = await page.evaluate(
            "() => (document.querySelector('.chat-input-editor')?.innerText || '').trim()"
        )
        if not got:
            logger.warning("kimi: editor text is empty after typing (model selector popup may be stealing focus)")
            return False
        if got != prompt.strip():
            logger.warning(
                "kimi: editor text mismatch (got %d chars vs expected %d chars)",
                len(got), len(prompt),
            )
            # Continue anyway if there's at least some text.
            if len(got) < len(prompt) / 2:
                return False

        # Submit with Enter.
        await page.keyboard.press("Enter")
        await asyncio.sleep(1)
        return True

    async def _read_latest_message(self, page) -> str:
        return await page.evaluate(
            """() => {
                // Kimi renders assistant bubbles in a chat-message list.  We
                // pick the LAST visible block whose own text is non-trivial
                // and not part of the input UI.
                const all = Array.from(document.querySelectorAll('div, p, section, article'));
                const candidates = [];
                for (const el of all) {
                    const t = (el.innerText || '').trim();
                    if (t.length < 20 || t.length > 3000) continue;
                    const cls = String(el.getAttribute('class') || '').toLowerCase();
                    if (/kimi-input|chat-input|user-input|ask anything/i.test(cls)) continue;
                    if (el.closest('textarea')) continue;
                    if (/(message|chat-item|response|markdown|assistant)/i.test(cls)) {
                        candidates.push(t);
                    }
                }
                return candidates.length ? candidates[candidates.length - 1] : '';
            }"""
        )
