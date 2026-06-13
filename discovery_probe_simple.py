
import asyncio
from playwright.async_api import async_playwright

async def run():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        )
        page = await context.new_page()

        requests_log = []
        async def handle_request(request):
            if "arena.ai" in request.url:
                requests_log.append({
                    "url": request.url,
                    "method": request.method,
                    "post_data": request.post_data
                })
        
        page.on("request", handle_request)

        print("Navigating to arena.ai/text/direct...")
        try:
            # Use a longer timeout and wait for 'domcontentloaded'
            await page.goto("https://arena.ai/text/direct", wait_until="domcontentloaded", timeout=60000)
            
            await page.screenshot(path="discovery_snapshot.png")
            content = await page.content()
            with open("discovery_page.html", "w", encoding="utf-8") as f:
                f.write(content)
            
            print("Page captured.")
        except Exception as e:
            print(f"Error: {e}")
            await page.screenshot(path="error_snapshot.png")

        with open("network_requests.txt", "w") as f:
            for req in requests_log:
                f.write(f"URL: {req['url']}\nMethod: {req['method']}\nData: {req['post_data']}\n{'-'*40}\n")

        await browser.close()

if __name__ == "__main__":
    asyncio.run(run())
