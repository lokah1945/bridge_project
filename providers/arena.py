
from .base import BaseProvider
from typing import Any, Dict, List
import asyncio

class ArenaProvider(BaseProvider):
    MODALITIES = {
        "text": "https://arena.ai/text/direct",
        "search": "https://arena.ai/search/direct",
        "image": "https://arena.ai/image/direct",
        "code": "https://arena.ai/code/direct"
    }

    async def list_models(self, modality="text") -> List[str]:
        url = self.MODALITIES.get(modality, self.MODALITIES["text"])
        page = await self._setup_browser()
        try:
            await page.goto(url, wait_until="networkidle")
            all_found_models = set()
            selects = await page.query_selector_all('select')
            for s in selects:
                options = await s.evaluate('el => Array.from(el.options).map(o => o.innerText.trim())')
                all_found_models.update(options)
            dropdown_triggers = await page.query_selector_all('text="Model"')
            for trigger in dropdown_triggers:
                try:
                    await trigger.click()
                    await asyncio.sleep(0.5)
                    items = await page.query_selector_all('[role="option"], .model-item, .dropdown-item')
                    for item in items:
                        text = await item.inner_text()
                        if text: all_found_models.add(text.strip())
                except: continue
            return list(all_found_models)
        finally:
            await page.close()

    async def execute(self, model_id: str, prompt: str, params: Dict[str, Any]) -> str:
        modality = params.get("modality", "text")
        url = self.MODALITIES.get(modality, self.MODALITIES["text"])
        page = await self._setup_browser()
        try:
            await page.goto(url, wait_until="networkidle")
            try:
                await page.click('text="Model"', timeout=5000)
                await page.click(f'text="{model_id}"')
            except:
                await page.select_option('select', label=model_id)
            await page.fill('textarea', prompt)
            await page.keyboard.press("Enter")
            await page.wait_for_selector('.response-bubble, .chat-message-content', timeout=60000)
            messages = await page.query_selector_all('.response-bubble, .chat-message-content')
            return await messages[-1].inner_text()
        finally:
            await self.context.clear_cookies()
            await page.close()
