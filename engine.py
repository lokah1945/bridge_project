
import asyncio
from playwright.async_api import async_playwright

class ArenaEngine:
    def __init__(self):
        self.browser = None
        self.context = None
        self.page = None

    async def start(self):
        pw = await async_playwright().start()
        self.browser = await pw.chromium.launch(
            headless=True, 
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-web-security",
                "--disable-features=IsolateOrigins,site-per-process"
            ]
        )
        self.context = await self.browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            viewport={'width': 1920, 'height': 1080}
        )
        self.page = await self.context.new_page()
        
        await self.page.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {
                get: () => undefined
            });
        """)
        
        await self.page.goto("https://arena.ai/text/direct", wait_until="networkidle")
        print("[Engine] Browser started and manual stealth applied.")

    async def _get_model_combobox(self):
        # There are usually two comboboxes: Mode and Model.
        # We want the one that likely controls the model.
        comboboxes = await self.page.query_selector_all("button[role='combobox']")
        for cb in comboboxes:
            if await cb.is_visible():
                text = await cb.inner_text()
                # The model selector usually contains the name of the current model
                # while the mode selector contains 'Direct', 'Battle', etc.
                if "Direct" not in text and "Battle" not in text and "Agent" not in text:
                    return cb
        
        # Fallback: return the second one if the first is the mode selector
        if len(comboboxes) > 1:
            return comboboxes[1]
        return comboboxes[0] if comboboxes else None

    async def get_models(self):
        try:
            cb = await self._get_model_combobox()
            if not cb:
                raise Exception("Model combobox not found")
            
            await cb.click()
            await self.page.wait_for_selector("[role='listbox'], .popover-content", timeout=5000)
            
            option_selectors = ["[role='option']", ".model-option", "div[data-model-id]"]
            for selector in option_selectors:
                elements = await self.page.query_selector_all(selector)
                if elements:
                    models = []
                    for el in elements:
                        text = await el.inner_text()
                        # Filter out modes
                        if text and not any(m in text for m in ["Battle", "Agent", "Direct", "Side by Side"]):
                            models.append(text)
                    if models:
                        return list(set(models))
            return []
        except Exception as e:
            print(f"[Engine] Error fetching models: {e}")
            return []

    async def chat_stream(self, model_name, prompt):
        try:
            cb = await self._get_model_combobox()
            if not cb:
                raise Exception("Model combobox not found")
            
            await cb.click()
            
            options = await self.page.query_selector_all("[role='option'], div, span")
            target_option = None
            for opt in options:
                text = await opt.inner_text()
                if model_name.lower() in text.lower():
                    target_option = opt
                    break
            
            if not target_option:
                raise Exception(f"Model {model_name} not found in dropdown")
                
            await target_option.click()
            
            textarea = await self.page.wait_for_selector("textarea", timeout=10000)
            await textarea.fill(prompt)
            await self.page.keyboard.press("Enter")
            
            previous_text = ""
            await asyncio.sleep(2)
            
            while True:
                responses = await self.page.query_selector_all(".bot-response-text, [data-testid='bot-response'], .markdown, div")
                if not responses:
                    break
                
                current_text = await responses[-1].inner_text()
                if current_text == previous_text:
                    send_btn = await self.page.query_selector("button[aria-label*='Send'], button:has-text('Send')")
                    if send_btn and await send_btn.is_visible():
                        break
                    await asyncio.sleep(0.5)
                else:
                    delta = current_text[len(previous_text):]
                    previous_text = current_text
                    yield delta
                    
        except Exception as e:
            yield f"Error: {str(e)}"

    async def stop(self):
        if self.browser:
            await self.browser.close()
