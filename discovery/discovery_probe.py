
import asyncio
from playwright.async_api import async_playwright
from playwright_extra import stealth_async
import json

class DiscoveryProbe:
    def __init__(self, provider_url, session_data=None):
        self.url = provider_url
        self.session_data = session_data
        self.audit_results = {
            "models": [],
            "tools": [],
            "selectors": {},
            "navigation": []
        }

    async def run_audit(self):
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=False) # Headfull for visual verification
            context = await browser.new_context(
                user_agent=self.session_data.get("user_agent") if self.session_data else "Mozilla/5.0..."
            )
            
            # Apply Stealth
            page = await context.new_page()
            await stealth_async(page)
            
            # Apply CDP Overrides
            cdp = await page.context().new_CDPSession(page)
            await cdp.send('Page.addScriptToEvaluateOnNewDocument', {
                'source': 'Object.defineProperty(navigator, "webdriver", {get: () => undefined});'
            })

            if self.session_data and self.session_data.get("cookies"):
                await context.add_cookies(self.session_data["cookies"])

            print(f"[*] Probing {self.url}...")
            await page.goto(self.url, wait_until="networkidle")

            # 1. Discover Models
            await self.probe_models(page)
            # 2. Discover Tools
            await self.probe_tools(page)
            # 3. Discover Navigation
            await self.probe_navigation(page)

            await browser.close()
            return self.audit_results

    async def probe_models(self, page):
        print("[+] Auditing Models...")
        # We try common selectors for model dropdowns
        selectors = ['select', '.model-selector', '[role="combobox"]', '.model-dropdown']
        for sel in selectors:
            try:
                elements = await page.query_selector_all(sel)
                if elements:
                    for el in elements:
                        options = await el.inner_text()
                        self.audit_results["models"].append({"selector": sel, "content": options})
            except: pass

    async def probe_tools(self, page):
        print("[+] Auditing Tools...")
        # Look for keywords in buttons/toggles
        keywords = ['Search', 'Research', 'Think', 'Upload', 'Canvas', 'Agent', 'Image']
        for kw in keywords:
            try:
                el = await page.get_by_text(kw).first
                if await el.is_visible():
                    # Try to find the selector
                    selector = await el.evaluate('node => node.outerHTML')
                    self.audit_results["tools"].append({"feature": kw, "html": selector})
            except: pass

    async def probe_navigation(self, page):
        print("[+] Auditing Navigation...")
        links = await page.query_selector_all('a')
        for link in links:
            href = await link.get_attribute('href')
            text = await link.inner_text()
            if href:
                self.audit_results["navigation"].append({"text": text, "href": href})

async def main():
    # Example for Arena
    probe = DiscoveryProbe("https://arena.ai/text/direct")
    results = await probe.run_audit()
    print(json.dumps(results, indent=2))

if __name__ == "__main__":
    asyncio.run(main())
