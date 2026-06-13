
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional
import asyncio
from playwright.async_api import async_playwright, Page, BrowserContext

class BaseProvider(ABC):
    def __init__(self, session_data: Dict[str, Any]):
        self.session_data = session_data
        self.cookies = session_data.get("cookies", [])
        self.user_agent = session_data.get("user_agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")
        self.browser = None
        self.context = None

    async def _setup_browser(self) -> Page:
        if not self.browser:
            self.playwright = await async_playwright().start()
            self.browser = await self.playwright.chromium.launch(
                headless=True,
                args=['--disable-blink-features=AutomationControlled']
            )
            self.context = await self.browser.new_context(user_agent=self.user_agent)
            if self.cookies:
                await self.context.add_cookies(self.cookies)

        page = await self.context.new_page()
        
        # Manual Stealth Implementation via CDP
        cdp = await page.context().new_CDPSession(page)
        await cdp.send('Page.addScriptToEvaluateOnNewDocument', {
            'source': '''
                Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
                Object.defineProperty(navigator, 'languages', {get: () => ['en-US', 'en']});
                Object.defineProperty(window, 'chrome', {get: () => ({runtime: {})} );
            '''
        })
        await cdp.send('Network.setExtraHTTPHeaders', {
            'headers': {
                'sec-ch-ua': '"Chromium";v="124", "Google Chrome";v="124", "Not-A brand";v="//"',
                'sec-ch-ua-mobile': '?0',
                'sec-ch-ua-platform': '"Windows"',
            }
        })
        return page

    @abstractmethod
    async def list_models(self, **kwargs) -> List[str]:
        pass

    @abstractmethod
    async def execute(self, model_id: str, prompt: str, params: Dict[str, Any]) -> str:
        pass

    async def cleanup(self):
        if self.browser:
            await self.browser.close()
            await self.playwright.stop()
