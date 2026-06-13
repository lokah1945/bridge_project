
import os
import json
import asyncio
import httpx
from datetime import datetime, timedelta
from typing import Any, Dict, Optional, List
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import StreamingResponse
from dotenv import load_dotenv
from cryptography.fernet import Fernet
import uvicorn

from registry import registry
from providers.arena import ArenaProvider
from providers.qwen import QwenProvider
from providers.deepseek import DeepSeekProvider

load_dotenv()

# --- CONFIGURATION ---
MODEL_CACHE_FILE = "model.json"
CACHE_INTERVAL = 3600 # 60 minutes

# Register providers
registry.register("arena", ArenaProvider)
registry.register("qwen", QwenProvider)
registry.register("deepseek", DeepSeekProvider)

class SessionManager:
    def __init__(self, session_dir="sessions"):
        self.session_dir = session_dir
        self.key = os.getenv("ENCRYPTION_KEY")
        if not self.key:
            self.key = Fernet.generate_key().decode()
            with open(".env", "a") as f: f.write(f"\\nENCRYPTION_KEY={self.key}")
        self.cipher = Fernet(self.key.encode())
        if not os.path.exists(self.session_dir): os.makedirs(self.session_dir)

    def _get_file_path(self, provider: str):
        return os.path.join(self.session_dir, f"{provider}.bin")

    def save_session(self, provider: str, data: Dict[str, Any]):
        data["_saved_at"] = datetime.now().isoformat()
        encrypted_data = self.cipher.encrypt(json.dumps(data).encode())
        with open(self._get_file_path(provider), "wb") as f: f.write(encrypted_data)

    def load_session(self, provider: str) -> Optional[Dict[str, Any]]:
        path = self._get_file_path(provider)
        if os.path.exists(path):
            try:
                with open(path, "rb") as f: encrypted_data = f.read()
                return json.loads(self.cipher.decrypt(encrypted_data))
            except: return None
        return None

    def is_expired(self, session_data: Dict[str, Any]) -> bool:
        ttl = int(os.getenv("SESSION_TTL_HOURS", 24))
        saved_at_str = session_data.get("_saved_at")
        if not saved_at_str: return True
        saved_at = datetime.fromisoformat(saved_at_str)
        return datetime.now() > saved_at + timedelta(hours=ttl)

app = FastAPI(title="Bridge-Client Production Gateway")
session_manager = SessionManager()
BRIDGE_SERVER_URL = os.getenv("BRIDGE_SERVER_URL", "http://host.zerotier.my.id:9877")

async def get_effective_session(provider: str):
    session = session_manager.load_session(provider)
    if not session or session_manager.is_expired(session):
        async with httpx.AsyncClient() as client:
            try:
                resp = await client.get(f"{BRIDGE_SERVER_URL}/get-session/{provider}", timeout=10)
                if resp.status_code == 200:
                    session = resp.json()
                    session_manager.save_session(provider, session)
                else:
                    if session: return session
                    raise Exception(f"Server failed to provide session: {resp.status_code}")
            except Exception as e:
                if session: return session
                raise Exception(f"Authentication Error: {str(e)}")
    return session

# --- MODEL CACHE SYSTEM ---
async def update_model_cache():
    """Background task to discover models and save them to model.json."""
    print("[Cache] Updating model cache...")
    all_models = []
    providers_map = {
        "arena": ArenaProvider, 
        "qwen": QwenProvider, 
        "deepseek": DeepSeekProvider
    }
    
    for name, provider_cls in providers_map.items():
        try:
            session = await get_effective_session(name)
            adapter = provider_cls(session)
            
            if name == "arena":
                from providers.arena import ArenaProvider
                for mod in ArenaProvider.MODALITIES.keys():
                    models = await adapter.list_models(modality=mod)
                    for m in models:
                        all_models.append({"id": f"bridge/arena/{mod}/{m}", "object": "model", "provider": "arena"})
            else:
                if hasattr(adapter, 'list_models'):
                    models = await adapter.list_models()
                    for m in models:
                        all_models.append({"id": f"bridge/{name}/{m}", "object": "model", "provider": name})
            
            await adapter.cleanup()
        except Exception as e:
            print(f"[Cache Error] {name}: {e}")

    with open(MODEL_CACHE_FILE, "w") as f:
        json.dump({
            "last_updated": datetime.now().isoformat(),
            "models": all_models
        }, f, indent=2)
    print(f"[Cache] Successfully updated {len(all_models)} models to {MODEL_CACHE_FILE}")

async def model_cache_loop():
    """Loop to update cache every 60 minutes."""
    while True:
        try:
            await update_model_cache()
        except Exception as e:
            print(f"[Cache Loop Error] {e}")
        await asyncio.sleep(CACHE_INTERVAL)

@app.on_event("startup")
async def startup_event():
    # Initial cache update
    asyncio.create_task(update_model_cache())
    # Start background loop
    asyncio.create_task(model_cache_loop())

@app.get("/v1/models")
async def list_models():
    if not os.path.exists(MODEL_CACHE_FILE):
        # Try one last emergency sync
        await update_model_cache()
        if not os.path.exists(MODEL_CACHE_FILE):
            raise HTTPException(status_code=503, detail="Model cache not yet initialized.")
    
    with open(MODEL_CACHE_FILE, "r") as f:
        data = json.load(f)
    
    return {"object": "list", "data": data["models"]}

@app.post("/v1/chat/completions")
async def chat_completions(request: Request):
    body = await request.json()
    model_target = body.get("model")
    messages = body.get("messages", [])
    extra_params = body.get("extra_params", {})
    stream = body.get("stream", False)

    if not model_target or "/" not in model_target:
        raise HTTPException(status_code=400, detail="Use bridge/provider/model format")

    parts = model_target.split("/")
    provider_name = parts[1]
    
    if provider_name == "arena":
        if len(parts) < 4: raise HTTPException(status_code=400, detail="Arena requires modality: bridge/arena/<modality>/<model>")
        modality, model_id = parts[2], parts[3]
    else:
        model_id = parts[2]
        modality = "text"

    prompt = messages[-1]["content"] if messages else ""
    if not prompt: raise HTTPException(status_code=400, detail="No prompt provided")

    try:
        session = await get_effective_session(provider_name)
        provider_cls = registry.get_provider_class(provider_name)
        if not provider_cls:
            raise HTTPException(status_code=404, detail=f"Provider {provider_name} not registered")
        
        adapter = provider_cls(session)
        if provider_name == "arena":
            extra_params["modality"] = modality
            
        res = await adapter.execute(model_id, prompt, extra_params)
        await adapter.cleanup()

        if stream:
            async def generate():
                for char in res:
                    yield f"data: {json.dumps({'choices': [{'delta': {'content': char}}]})}\n\n"
                    await asyncio.sleep(0.01)
                yield "data: [DONE]\n\n"
            return StreamingResponse(generate(), media_type="text/event-stream")
        else:
            return {
                "id": "chatcmpl-bridge",
                "object": "chat.completion",
                "created": int(datetime.now().timestamp()),
                "model": model_target,
                "choices": [{"index": 0, "message": {"role": "assistant", "content": res}, "finish_reason": "stop"}]
            }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", 8000)))
