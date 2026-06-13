
import asyncio
import json
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse
from playwright.async_api import async_playwright
from registry import registry
from typing import Any, Dict

app = FastAPI(title="Bridge-Server Hub")

# Global State
browser_context = {
    "browser": None,
    "context": None,
    "sessions": {
        "arena": {"cookies": [], "user_agent": "Mozilla/5.0..."},
        "qwen": {"cookies": [], "user_agent": "Mozilla/5.0..."},
    }
}

@app.on_event("startup")
async def startup():
    # In Windows Headfull, this would launch a real browser
    # --remote-debugging-port=99876 allows external attachment
    pw = await async_playwright().start()
    browser = await pw.chromium.launch(
        headless=False, # Headfull as per Master Prompt
        args=["--remote-debugging-port=99876"]
    )
    context = await browser.new_context()
    browser_context["browser"] = browser
    browser_context["context"] = context
    print("[Bridge-Server] Hub started. Browser active on port 99876.")

@app.get("/get-session/{provider}")
async def get_session(provider: str):
    provider = provider.lower()
    if provider not in browser_context["sessions"]:
        raise HTTPException(status_code=404, detail="Provider session not found")
    
    return browser_context["sessions"][provider]

@app.post("/invoke")
async def invoke_bridge(request: Request):
    body = await request.json()
    target = body.get("target") # Format: bridge/provider/model
    payload = body.get("payload", {})

    if not target or "/" not in target:
        raise HTTPException(status_code=400, detail="Invalid target format. Use bridge/provider/model")

    parts = target.split("/")
    if parts[0] != "bridge" or len(parts) < 3:
        raise HTTPException(status_code=400, detail="Invalid naming convention")

    provider_name = parts[1]
    model_id = parts[2]

    # 1. Dynamic Lookup Provider
    provider_class = registry.get_provider_class(provider_name)
    if not provider_class:
        raise HTTPException(status_code=404, detail=f"Provider '{provider_name}' not found")

    # 2. Inject Session Data
    session_data = browser_context["sessions"].get(provider_name, {})
    provider_instance = provider_class(session_data)

    # 3. Execute
    try:
        result = await provider_instance.handle_request(model_id, payload)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=99876)
