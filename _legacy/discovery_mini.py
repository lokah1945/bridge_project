
import asyncio
from playwright.async_api import async_playwright

async def probe_single(name, url, probe_fn):
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")
        page = await context.new_page()
        await page.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined});")
        
        print(f"Probing {name}...")
        try:
            await page.goto(url, wait_until="networkidle", timeout=60000)
            result = await probe_fn(page)
            print(f"Done {name}.")
            return result
        except Exception as e:
            print(f"Error probing {name}: {e}")
            return {"error": str(e)}
        finally:
            await browser.close()

async def probe_arena_text(page):
    try:
        await page.click("button[role='combobox']")
        await page.wait_for_selector("[role='listbox']", timeout=5000)
        return await page.eval_on_selector_all("[role='option']", "elements => elements.map(e => e.innerText)")
    except: return []

async def probe_qwen(page):
    try:
        await page.click("button[role='combobox']")
        expand = await page.query_selector("text='Expand More'")
        if expand: await expand.click()
        await page.wait_for_selector("[role='listbox']", timeout=5000)
        models = await page.eval_on_selector_all("[role='option']", "elements => elements.map(e => e.innerText)")
        return {"models": models}
    except: return {"error": "failed"}

async def main():
    arena_text = await probe_single("Arena Text", "https://arena.ai/text/direct", probe_arena_text)
    qwen = await probe_single("Qwen", "https://chat.qwen.ai/?temporary-chat=true", probe_qwen)
    print("\n--- RESULTS ---")
    print(f"Arena Text Models: {arena_text}")
    print(f"Qwen Data: {qwen}")

if __name__ == "__main__":
    asyncio.run(main())
