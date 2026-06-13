
import asyncio
from playwright.async_api import async_playwright

async def run():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        )
        page = await context.new_page()
        await page.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
        
        await page.goto("https://arena.ai/text/direct", wait_until="networkidle")
        
        comboboxes = await page.query_selector_all("button[role='combobox']")
        print(f"Found {len(comboboxes)} comboboxes.")
        
        for i, cb in enumerate(comboboxes):
            print(f"Clicking combobox {i}...")
            await cb.click()
            await asyncio.sleep(2)
            
            # Dump all visible text to see what's in the dropdown
            text = await page.inner_text("body")
            print(f"Body text after clicking combobox {i}:\n{text[:1000]}...")
            
        await browser.close()

if __name__ == "__main__":
    asyncio.run(run())
