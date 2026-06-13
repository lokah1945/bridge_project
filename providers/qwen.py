
from .base import BaseProvider
from typing import Any, Dict, List
import asyncio

class QwenProvider(BaseProvider):
    URL = "https://chat.qwen.ai/?temporary-chat=true"

    async def list_models(self) -> List[str]:
        page = await self._setup_browser()
        try:
            await page.goto(self.URL, wait_until="networkidle")
            all_models = set()
            try:
                selector = await page.query_selector('.model-selector, [role="combobox"], text="Model"')
                if selector:
                    await selector.click()
                    await asyncio.sleep(0.5)
                    expand_selectors = ['text="Expand More"', 'text="More"', '.expand-btn', '.show-all']
                    for exp in expand_selectors:
                        try:
                            exp_btn = await page.query_selector(exp)
                            if exp_btn and await exp_btn.is_visible():
                                await exp_btn.click()
                                await asyncio.sleep(0.5)
                        except: continue
                    options = await page.query_selector_all('[role="option"], .model-option, .dropdown-item, li')
                    for opt in options:
                        text = await opt.inner_text()
                        if text and len(text) < 100:
                            all_models.add(text.strip())
            except Exception as e:
                print(f"Qwen Discovery Error: {e}")
            return list(all_models)
        finally:
            await page.close()

    async def execute(self, model_id: str, prompt: str, params: Dict[str, Any]) -> str:
        thinking = params.get("thinking", "auto")
        tools = params.get("tools", True)
        page = await self._setup_browser()
        try:
            await page.goto(self.URL, wait_until="networkidle")
            try:
                await page.click('.model-selector, text="Model"', timeout=5000)
                try:
                    expand_btn = await page.query_selector('text="Expand More"')
                    if expand_btn: await expand_btn.click()
                except: pass
                await page.click(f'text="{model_id}"')
            except: pass
            if thinking != "auto":
                try:
                    await page.click('.thinking-mode-dropdown', timeout=5000)
                    await page.click(f'text="{thinking}"')
                except: pass
            if not tools:
                try:
                    await page.click('.tool-toggle-btn', timeout=5000)
                except: pass
            await page.fill('textarea', prompt)
            await page.keyboard.press("Enter")
            await page.wait_for_selector('.chat-message-content', timeout=60000)
            messages = await page.query_selector_all('.chat-message-content')
            return await messages[-1].inner_text()
        finally:
            await self.context.clear_cookies()
            await page.close()
