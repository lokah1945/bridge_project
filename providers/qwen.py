"""Qwen.ai provider automation."""
import asyncio
from typing import Any, Dict, List

from providers.base import BaseProvider
from client.config import settings


class QwenProvider(BaseProvider):
    URL = "https://chat.qwen.ai/?temporary-chat=true"

    async def list_models(self, **kwargs) -> List[str]:
        page = await self._setup(self.URL)
        try:
            models = set()
            selector = await page.query_selector(
                '.model-selector, [role="combobox"], button:has-text("Model")'
            )
            if not selector:
                return []
            await selector.click()
            await asyncio.sleep(0.5)

            # Try to expand the full list.
            expand_selectors = ['text="Expand More"', 'text="More"', '.expand-btn', '.show-all']
            for exp in expand_selectors:
                try:
                    btn = await page.query_selector(exp)
                    if btn and await btn.is_visible():
                        await btn.click()
                        await asyncio.sleep(0.5)
                except Exception:
                    continue

            option_selectors = [
                '[role="option"]',
                ".model-option",
                ".dropdown-item",
                "li",
                ".model-item",
            ]
            for sel in option_selectors:
                options = await page.query_selector_all(sel)
                for opt in options:
                    text = await opt.inner_text()
                    if text and len(text) < 100:
                        models.add(text.strip())
            await page.keyboard.press("Escape")
            return sorted(models)
        finally:
            await self.cleanup()

    async def execute(self, model_id: str, prompt: str, params: Dict[str, Any]) -> str:
        thinking = params.get("thinking", "auto")
        tools = params.get("tools", True)

        page = await self._setup(self.URL)
        try:
            await self._select_model(model_id)
            await self._configure_thinking(thinking)
            await self._configure_tools(tools)

            if not await self._fill_textarea(prompt):
                raise RuntimeError("Qwen chat textarea not found")

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
        try:
            await page.click('.model-selector, button:has-text("Model")', timeout=5000)
            try:
                expand_btn = await page.query_selector('text="Expand More"')
                if expand_btn and await expand_btn.is_visible():
                    await expand_btn.click()
                    await asyncio.sleep(0.3)
            except Exception:
                pass
            await page.click(f'text="{model_id}"', timeout=5000)
        except Exception as e:
            if settings.debug:
                print(f"[QwenProvider] _select_model failed: {e}")

    async def _configure_thinking(self, thinking: str) -> None:
        page = self.page
        if page is None or thinking == "auto":
            return
        try:
            await page.click('.thinking-mode-dropdown, button:has-text("Thinking")', timeout=5000)
            await page.click(f'text="{thinking}"', timeout=3000)
        except Exception as e:
            if settings.debug:
                print(f"[QwenProvider] thinking config failed: {e}")

    async def _configure_tools(self, tools: bool) -> None:
        page = self.page
        if page is None:
            return
        try:
            btn = await page.query_selector('.tool-toggle-btn, button:has-text("Tools")')
            if btn:
                current = await btn.get_attribute("aria-pressed") or "false"
                active = current.lower() in ("true", "1")
                if active != tools:
                    await btn.click()
        except Exception as e:
            if settings.debug:
                print(f"[QwenProvider] tools config failed: {e}")

    async def _submit_prompt(self) -> None:
        page = self.page
        if page is None:
            return
        try:
            await page.keyboard.press("Enter")
        except Exception as e:
            if settings.debug:
                print(f"[QwenProvider] submit failed: {e}")
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
                ".chat-message-content",
                ".response-bubble",
                ".markdown",
                "[data-testid='assistant-message']",
                ".message-content",
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
                stable_count += 1
                if stable_count >= 3:
                    return current_text

        raise TimeoutError(f"Qwen response timeout after {max_wait}s")

    async def _stateless_cleanup(self) -> None:
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
