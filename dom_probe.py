
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
        
        print("Navigating to arena.ai/text/direct...")
        await page.goto("https://arena.ai/text/direct", wait_until="networkidle")
        
        # Try to find the model selector
        print("Looking for selectors...")
        buttons = await page.query_selector_all("button")
        print(f"Found {len(buttons)} buttons.")
        for i, btn in enumerate(buttons):
            text = await btn.inner_text()
            role = await btn.get_attribute("role")
            if "model" in text.lower() or role == "combobox":
                print(f"Button {i}: text='{text}', role='{role}'")

        await page.screenshot(path="dom_debug.png")
        html = await page.content()
        with open("dom_debug.html", "w") as f:
            f.write(html)
            
        await browser.close()

if __name__ == "__main__":
    asyncio.run(run())
