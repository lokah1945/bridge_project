"""DeepSeek provider automation."""
import asyncio
from typing import Any, Dict, List

from providers.base import BaseProvider
from client.config import settings


class DeepSeekProvider(BaseProvider):
    URL = "https://chat.deepseek.com/"

    async def list_models(self, **kwargs) -> List[str]:
        page = await self._setup(self.URL)
        try:
            models = set()
            selector = await page.query_selector(
                '.model-selector, [role="combobox"], button[aria-haspopup="listbox"]'
            )
            if selector:
                await selector.click()
                await asyncio.sleep(0.5)
                options = await page.query_selector_all(
                    '[role="option"], .model-option, .dropdown-item, li'
                )
                for opt in options:
                    text = await opt.inner_text()
                    if text:
                        models.add(text.strip())
                await page.keyboard.press("Escape")
            return sorted(models) if models else ["deepseek-v3", "deepseek-coder"]
        finally:
            await self.cleanup()

    async def execute(self, model_id: str, prompt: str, params: Dict[str, Any]) -> str:
        mode = params.get("mode", "fast")
        thinking = params.get("thinking", False)
        search = params.get("search", False)

        page = await self._setup(self.URL)
        try:
            await self._select_model(model_id)

            if mode == "expert":
                await self._toggle("mode-expert-toggle", "Expert")
            if thinking:
                await self._toggle("think-toggle", "DeepThink")
            if search:
                await self._toggle("search-toggle", "Search")

            if not await self._fill_textarea(prompt):
                raise RuntimeError("DeepSeek chat textarea not found")

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
            await page.click('.model-selector, button[aria-haspopup="listbox"]', timeout=5000)
            await page.click(f'text="{model_id}"', timeout=5000)
        except Exception as e:
            if settings.debug:
                print(f"[DeepSeekProvider] _select_model failed: {e}")

    async def _toggle(self, class_name: str, text_label: str) -> None:
        page = self.page
        if page is None:
            return
        selectors = [
            f".{class_name}",
            f'button:has-text("{text_label}")',
            f'text="{text_label}"',
        ]
        for sel in selectors:
            try:
                await page.click(sel, timeout=5000)
                return
            except Exception:
                continue
        if settings.debug:
            print(f"[DeepSeekProvider] toggle failed: {class_name} / {text_label}")

    async def _submit_prompt(self) -> None:
        page = self.page
        if page is None:
            return
        try:
            await page.keyboard.press("Enter")
        except Exception as e:
            if settings.debug:
                print(f"[DeepSeekProvider] submit failed: {e}")
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
                ".ds-message",
                ".chat-message-content",
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

        raise TimeoutError(f"DeepSeek response timeout after {max_wait}s")

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
