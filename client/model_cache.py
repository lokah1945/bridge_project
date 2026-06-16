"""Model Cache System: periodic discovery + persistent model.json."""
import asyncio
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from client.config import settings, MODEL_CACHE_FILE
from client.session_manager import SessionManager
from registry import registry
from providers.arena import ArenaProvider
from providers.qwen import QwenProvider
from providers.deepseek import DeepSeekProvider

# Register providers in case registry hasn't been populated yet.
registry.register("arena", ArenaProvider)
registry.register("qwen", QwenProvider)
registry.register("deepseek", DeepSeekProvider)


def _build_model_id(provider: str, model: str, modality: Optional[str] = None) -> str:
    if provider == "arena" and modality:
        return f"bridge/arena/{modality}/{model}"
    return f"bridge/{provider}/{model}"


async def update_cache(session_manager: Optional[SessionManager] = None) -> Dict[str, Any]:
    """Discover models from all providers and write model.json.
    
    This function is designed to be resilient — browser failures on one provider
    will not prevent other providers from being cached.
    """
    session_manager = session_manager or SessionManager()
    all_models: List[Dict[str, Any]] = []

    providers_map = {
        "arena": ArenaProvider,
        "qwen": QwenProvider,
        "deepseek": DeepSeekProvider,
    }

    for name, provider_cls in providers_map.items():
        try:
            # Get session first (this can fail if bridge-server is unreachable)
            try:
                session = await session_manager.get_effective_session(name)
            except Exception as sess_err:
                if settings.debug:
                    print(f"[ModelCache] Failed to get session for {name}: {sess_err}")
                continue

            adapter = provider_cls(session)

            if name == "arena":
                for mod in getattr(ArenaProvider, 'MODALITIES', {}).keys():
                    try:
                        models = await adapter.list_models(modality=mod)
                        for m in models:
                            all_models.append({
                                "id": _build_model_id("arena", m, mod),
                                "object": "model",
                                "owned_by": "arena",
                                "modality": mod,
                            })
                    except Exception as e:
                        if settings.debug:
                            print(f"[ModelCache] arena/{mod} discovery error: {e}")
            else:
                try:
                    models = await adapter.list_models()
                    for m in models:
                        all_models.append({
                            "id": _build_model_id(name, m),
                            "object": "model",
                            "owned_by": name,
                        })
                except Exception as e:
                    if settings.debug:
                        print(f"[ModelCache] {name} discovery error: {e}")

            await adapter.cleanup()
        except Exception as e:
            if settings.debug:
                print(f"[ModelCache] provider '{name}' failed completely: {e}")
            continue

    cache_data = {
        "last_updated": datetime.now().isoformat(),
        "models": all_models,
    }

    MODEL_CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(MODEL_CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(cache_data, f, indent=2)

    print(f"[ModelCache] Cached {len(all_models)} models to {MODEL_CACHE_FILE}")
    return cache_data


async def cache_loop(session_manager: Optional[SessionManager] = None) -> None:
    """Background loop that refreshes the cache every MODEL_CACHE_TTL_MIN."""
    session_manager = session_manager or SessionManager()
    while True:
        try:
            await update_cache(session_manager)
        except Exception as e:
            print(f"[ModelCache] background refresh failed: {e}")
        await asyncio.sleep(settings.model_cache_ttl_min * 60)


def get_cached_models() -> List[Dict[str, Any]]:
    """Read models from model.json. Returns empty list if cache missing."""
    if not MODEL_CACHE_FILE.exists():
        return []
    try:
        with open(MODEL_CACHE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data.get("models", [])
    except Exception as e:
        if settings.debug:
            print(f"[ModelCache] read failed: {e}")
        return []
