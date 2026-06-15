"""Arena.ai provider automation.

Supports text, search, image, and code modalities via direct endpoints.
"""
import asyncio
from typing import Any, Dict, List

from providers.base import BaseProvider
from client.config import settings


class ArenaProvider(BaseProvider):
    MODALITIES = {
        "text": "https://arena.ai/text/direct",
        "search": "https://arena.ai/search/direct",
        "image": "https://arena.ai/image/direct",
        "code": "https://arena.ai/code/direct",
    }

    async def list_models(self, modality: str = "text", **kwargs) -> List[str]:
        url = self.MODALITIES.get(modality, self.MODALITIES["text"])
        page = await self._setup(url)
        try:
            models = set()
            # Strategy 1: native <select> options.
            selects = await page.query_selector_all("select")
            for s in selects:
                try:
                    options = await s.evaluate(
                        "el => Array.from(el.options).map(o => o.innerText.trim())"
                    )
                    models.update(o for o in options if o)
                except Exception:
                    continue

            # Strategy 2: combobox / dropdown triggers.
            triggers = await page.query_selector_all(
                'button[role="combobox"], [aria-haspopup="listbox"], .model-selector, [data-testid="model-selector"]'
            )
            for trigger in triggers:
                try:
                    text = await trigger.inner_text()
                    if not text or any(x in text for x in ["Direct", "Battle", "Agent", "Side by Side"]):
                        continue
                    await trigger.click()
                    await asyncio.sleep(0.5)

                    option_selectors = [
                        '[role="option"]',
                        ".model-option",
                        ".dropdown-item",
                        "[data-model-id]",
                        "li",
                    ]
                    for sel in option_selectors:
                        items = await page.query_selector_all(sel)
                        for item in items:
                            t = await item.inner_text()
                            if t and not any(x in t for x in ["Battle", "Agent", "Direct", "Side by Side"]):
                                models.add(t.strip())
                    # Close the dropdown by pressing Escape.
                    await page.keyboard.press("Escape")
                except Exception as e:
                    if settings.debug:
                        print(f"[ArenaProvider] list_models trigger error: {e}")
                    continue

            return sorted(models)
        finally:
            await self.cleanup()

    async def execute(self, model_id: str, prompt: str, params: Dict[str, Any]) -> str:
        modality = params.get("modality", "text")
        temporary_chat = params.get("temporary_chat", True)
        aspect_ratio = params.get("aspect_ratio", "1:1")

        url = self.MODALITIES.get(modality, self.MODALITIES["text"])
        if temporary_chat and "?" not in url:
            url += "?temporary=true"
        elif temporary_chat:
            url += "&temporary=true"

        page = await self._setup(url)
        try:
            await self._select_model(model_id)

            if modality == "image":
                await self._set_aspect_ratio(aspect_ratio)

            if not await self._fill_textarea(prompt):
                raise RuntimeError("Arena chat textarea not found")

            await self._submit_prompt()
            response = await self._read_response()
            return response
        finally:
            await self._stateless_cleanup()
            await self.cleanup()

    async def _select_model(self, model_id: str) -> None:
        page = self.page
        if page is None:
            return

        # Try multiple strategies to select the model.
        strategies = [
            ("select", lambda: page.select_option("select", label=model_id)),
            ("text exact", lambda: page.click(f'text="{model_id}"', timeout=5000)),
            ("has-text", lambda: page.click(f'button:has-text("{model_id}")', timeout=5000)),
            ("option text", lambda: page.click(f'[role="option"]:has-text("{model_id}")', timeout=5000)),
        ]

        # Open model dropdown first if needed.
        dropdown_selectors = [
            'button[role="combobox"]',
            '[aria-haspopup="listbox"]',
            ".model-selector",
            '[data-testid="model-selector"]',
            'button:has-text("Model")',
        ]
        for sel in dropdown_selectors:
            try:
                handles = await page.query_selector_all(sel)
                for handle in handles:
                    text = await handle.inner_text()
                    if text and any(x in text for x in ["Direct", "Battle", "Agent", "Side by Side"]):
                        continue
                    if await handle.is_visible():
                        await handle.click()
                        await asyncio.sleep(0.3)
                        break
                else:
                    continue
                break
            except Exception as e:
                if settings.debug:
                    print(f"[ArenaProvider] _select_model dropdown open failed: {e}")
                continue

        # Try strategies in order.
        for name, action in strategies:
            try:
                await action()
                await asyncio.sleep(0.3)
                return
            except Exception as e:
                if settings.debug:
                    print(f"[ArenaProvider] _select_model strategy '{name}' failed: {e}")
                continue

        if settings.debug:
            print(f"[ArenaProvider] WARNING: Could not select model {model_id}; continuing with default")

    async def _set_aspect_ratio(self, aspect_ratio: str) -> None:
        page = self.page
        if page is None:
            return
        try:
            # Common labels: "1:1", "16:9", "9:16", "4:3"
            await page.click(f'text="{aspect_ratio}"', timeout=3000)
        except Exception as e:
            if settings.debug:
                print(f"[ArenaProvider] aspect ratio set failed: {e}")

    async def _submit_prompt(self) -> None:
        page = self.page
        if page is None:
            return
        try:
            await page.keyboard.press("Enter")
        except Exception as e:
            if settings.debug:
                print(f"[ArenaProvider] submit failed: {e}")
            raise RuntimeError("Failed to submit prompt") from e

    async def _read_response(self) -> str:
        page = self.page
        if page is None:
            raise RuntimeError("Browser page lost")

        max_wait = settings.request_timeout
        poll_interval = 0.5
        elapsed = 0.0
        previous_text = ""
        stable_count = 0

        while elapsed < max_wait:
            await asyncio.sleep(poll_interval)
            elapsed += poll_interval

            selectors = [
                ".bot-response-text",
                "[data-testid='bot-response']",
                ".markdown",
                ".chat-message-content",
                ".response-bubble",
                "[data-testid='assistant-message']",
            ]
            responses = []
            for sel in selectors:
                responses = await page.query_selector_all(sel)
                if responses:
                    break

            if not responses:
                continue

            current_text = ""
            for r in responses:
                try:
                    text = await r.inner_text()
                    if text:
                        current_text = text
                except Exception:
                    continue

            if current_text and current_text != previous_text:
                previous_text = current_text
                stable_count = 0
            elif current_text:
                # Text is stable; check if send button is back.
                try:
                    send_btn = await page.query_selector(
                        "button[aria-label*='Send'], button:has-text('Send'), button[type='submit']"
                    )
                    if send_btn and await send_btn.is_visible():
                        return current_text
                    stable_count += 1
                    if stable_count >= 3:  # 1.5 seconds of stable text
                        return current_text
                except Exception:
                    return current_text

        raise TimeoutError(f"Arena response timeout after {max_wait}s")

    async def _stateless_cleanup(self) -> None:
        """Clear cookies and local storage to avoid leaving history."""
        if self.context:
            try:
                await self.context.clear_cookies()
            except Exception:
                pass
        if self.page:
            try:
                await self.page.evaluate("() => { localStorage.clear(); sessionStorage.clear(); }")
            except Exception:
                pass
