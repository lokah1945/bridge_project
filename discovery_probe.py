
import asyncio
from playwright.async_api import async_playwright

async def probe_arena(page):
    urls = {"text": "https://arena.ai/text/direct", "search": "https://arena.ai/search/direct", "image": "https://arena.ai/image/direct", "code": "https://arena.ai/code/direct"}
    results = {}
    for modality, url in urls.items():
        print(f"Probing Arena {modality}...")
        await page.goto(url, wait_until="networkidle")
        try:
            await page.click("button[role='combobox']")
            await page.wait_for_selector("[role='listbox']", timeout=5000)
            models = await page.eval_on_selector_all("[role='option']", "elements => elements.map(e => e.innerText)")
            results[modality] = models
        except Exception as e: results[modality] = f"Error: {e}"
    return results

async def probe_qwen(page):
    print("Probing Qwen...")
    await page.goto("https://chat.qwen.ai/?temporary-chat=true", wait_until="networkidle")
    results = {"models": [], "features": {}}
    try:
        await page.click("button[role='combobox']")
        expand_btn = await page.query_selector("text='Expand More'")
        if expand_btn: await expand_btn.click()
        await page.wait_for_selector("[role='listbox']", timeout=5000)
        results["models"] = await page.eval_on_selector_all("[role='option']", "elements => elements.map(e => e.innerText)")
        thinking = await page.query_selector_all("text='Thinking'")
        results["features"]["thinking"] = [await el.inner_text() for el in thinking]
        tools = await page.query_selector_all("text='Tools'")
        results["features"]["tools"] = [await el.inner_text() for el in tools]
    except Exception as e: results["error"] = str(e)
    return results

async def probe_deepseek(page):
    print("Probing DeepSeek...")
    await page.goto("https://chat.deepseek.com", wait_until="networkidle")
    results = {"models": [], "features": {}}
    try:
        model_btn = await page.wait_for_selector("button[aria-haspopup='listbox']", timeout=5000)
        await model_btn.click()
        results["models"] = await page.eval_on_selector_all("[role='option']", "elements => elements.map(e => e.innerText)")
        think_btn = await page.query_selector("text='DeepThink'")
        results["features"]["thinking"] = "Found" if think_btn else "Not Found"
        search_btn = await page.query_selector("text='Search'")
        results["features"]["search"] = "Found" if search_btn else "Not Found"
    except Exception as e: results["error"] = str(e)
    return results

async def run():
    async with async_playwright() as p:
        # launch with a real browser to avoid detection and handle JS
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")
        page = await context.new_page()
        
        # Manual Stealth Implementation to avoid library conflicts
        await page.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
            window.chrome = { runtime: {} };
        """)

        print("--- STARTING COMPREHENSIVE DISCOVERY ---")
        arena_data = await probe_arena(page)
        qwen_data = await probe_qwen(page)
        deepseek_data = await probe_deepseek(page)
        
        with open("discovery_evidence.json", "w") as f:
            json.dump({"arena": arena_data, "qwen": qwen_data, "deepseek": deepseek_data}, f, indent=4)
        print("\n--- DISCOVERY COMPLETE. EVIDENCE SAVED TO discovery_evidence.json ---")
        await browser.close()

if __name__ == "__main__":
    asyncio.run(run())
