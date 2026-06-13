
from .base import BaseProvider
from typing import Any, Dict, List
import asyncio

class DeepSeekProvider(BaseProvider):
    URL = "https://chat.deepseek.com/"

    async def list_models(self) -> List[str]:
        """Aggressively scrape DeepSeek models."""
        page = await self._setup_browser()
        try:
            await page.goto(self.URL, wait_until="networkidle")
            
            all_models = set()
            try:
                # DeepSeek uses a custom model switcher
                selector = await page.query_selector('.model-selector, [role="combobox"], text="Model"')
                if selector:
                    await selector.click()
                    await asyncio.sleep(0.5)
                    options = await page.query_selector_all('[role="option"], .model-option, .dropdown-item')
                    for opt in options:
                        text = await opt.inner_text()
                        if text: all_models.add(text.strip())
            except Exception as e:
                print(f"DeepSeek Discovery Error: {e}")
                
            return list(all_models) if all_models else ["deepseek-v3", "deepseek-coder"]
        finally:
            await page.close()

    async def execute(self, model_id: str, prompt: str, params: Dict[str, Any]) -> str:
        mode = params.get("mode", "fast")
        thinking = params.get("thinking", False)
        search = params.get("search", False)
        
        page = await self._setup_browser()
        try:
            await page.goto(self.URL, wait_until="networkidle")

            try:
                await page.click('.model-selector, text="Model"', timeout=5000)
                await page.click(f'text="{model_id}"')
            except: pass

            if mode == "expert":
                try: await page.click('.mode-expert-toggle', timeout=5000)
                except: pass

            if thinking:
                try: await page.click('.think-toggle', timeout=5000)
                except: pass

            if search:
                try: await page.click('.search-toggle', timeout=5000)
                except: pass

            await page.fill('textarea', prompt)
            await page.keyboard.press("Enter")

            await page.wait_for_selector('.ds-message', timeout=60000)
            messages = await page.query_selector_all('.ds-message')
            return await messages[-1].inner_text()
        finally:
            await self.context.clear_cookies()
            await page.close()
