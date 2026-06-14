"""bridge-client FastAPI gateway.

Architecture: Session-Provider / Executor-Client (see MASTER PROMPT Bagian 4).

  bridge-server (Windows) = session authority only, runs headfull Chrome with
    manual login.  Exposes /get-session/<provider> returning the cookies +
    user-agent + headers needed to act as the logged-in user.

  bridge-client (Linux, this file) =
    - syncs encrypted sessions from BRIDGE_SERVER_URL into local Fernet files
    - launches Playwright headless, injects cookies, drives arena.ai /
      chat.qwen.ai / chat.deepseek.com directly
    - exposes an OpenAI-compatible API on PORT:
        GET  /v1/models
        POST /v1/chat/completions
        GET  /health

  Statelessness: each request creates a fresh provider instance + browser
  context; cookies are cleared after every execute() so the user account
  history is never polluted.  Qwen uses the ?temporary-chat=true endpoint.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import json
import logging
import os
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, AsyncIterator, Dict, List, Optional

import httpx
import uvicorn
from cryptography.fernet import Fernet, InvalidToken
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from providers.base import BaseProvider
from registry import ProviderRegistry

# --------------------------------------------------------------------- logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s | %(message)s",
)
logger = logging.getLogger("bridge.client")

# --------------------------------------------------------------------- config

load_dotenv(Path(__file__).parent / ".env")

BRIDGE_SERVER_URL: str = os.environ.get(
    "BRIDGE_SERVER_URL", "http://host.zerotier.my.id:9877"
).rstrip("/")
PORT: int = int(os.environ.get("PORT", "8000"))
SESSION_TTL_HOURS: int = int(os.environ.get("SESSION_TTL_HOURS", "24"))
MODEL_CACHE_REFRESH_MINUTES: int = int(
    os.environ.get("MODEL_CACHE_REFRESH_MINUTES", "60")
)
ENCRYPTION_KEY: str = os.environ.get("ENCRYPTION_KEY", "")

SESSIONS_DIR = Path(__file__).parent / "sessions"
SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
MODEL_CACHE_FILE = Path(__file__).parent / "model.json"


def _load_or_create_fernet_key() -> Fernet:
    """If .env has no ENCRYPTION_KEY, generate one and persist it."""
    global ENCRYPTION_KEY
    if not ENCRYPTION_KEY:
        ENCRYPTION_KEY = Fernet.generate_key().decode()
        env_path = Path(__file__).parent / ".env"
        with env_path.open("a") as f:
            f.write(f"\nENCRYPTION_KEY={ENCRYPTION_KEY}\n")
        logger.info("generated and persisted new ENCRYPTION_KEY")
    return Fernet(ENCRYPTION_KEY.encode())


# ===================================================================== Session

class SessionManager:
    """Persist encrypted session payloads to disk."""

    def __init__(self, fernet: Fernet):
        self.fernet = fernet

    def _path(self, provider: str) -> Path:
        return SESSIONS_DIR / f"{provider}.bin"

    def save_session(self, provider: str, data: Dict[str, Any]) -> None:
        payload = dict(data)
        payload["_saved_at"] = dt.datetime.now(dt.UTC).replace(tzinfo=None).isoformat() + "Z"
        token = self.fernet.encrypt(json.dumps(payload, default=str).encode())
        self._path(provider).write_bytes(token)

    def load_session(self, provider: str) -> Optional[Dict[str, Any]]:
        p = self._path(provider)
        if not p.exists():
            return None
        try:
            token = p.read_bytes()
            data = json.loads(self.fernet.decrypt(token).decode())
            return data
        except (InvalidToken, ValueError, OSError) as exc:
            logger.warning("load_session(%s) failed: %s", provider, exc)
            return None

    def is_expired(self, session: Dict[str, Any]) -> bool:
        saved = session.get("_saved_at")
        if not saved:
            return True
        try:
            t = dt.datetime.fromisoformat(saved.replace("Z", ""))
        except ValueError:
            return True
        age = dt.datetime.now(dt.UTC).replace(tzinfo=None) - t
        return age > dt.timedelta(hours=SESSION_TTL_HOURS)


# ===================================================================== Sync

async def fetch_session_from_server(
    provider: str, timeout: float = 20.0
) -> Optional[Dict[str, Any]]:
    url = f"{BRIDGE_SERVER_URL}/get-session/{provider}"
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.get(url)
    except httpx.HTTPError as exc:
        logger.warning("fetch_session_from_server(%s) network error: %s", provider, exc)
        return None
    if resp.status_code == 200:
        try:
            return resp.json()
        except ValueError as exc:
            logger.warning("fetch_session_from_server(%s) bad JSON: %s", provider, exc)
            return None
    logger.info(
        "fetch_session_from_server(%s) returned %s (body: %s)",
        provider, resp.status_code, resp.text[:200],
    )
    return None


# Some bridge-server profiles (e.g. arena) keep cookies for OTHER providers
# in the same Chromium user data dir.  When /get-session/<provider> returns
# 404 we can still drive that provider using a fallback session, because
# the cookie blob is identical.
PROVIDER_FALLBACKS: Dict[str, List[str]] = {
    "kimi": ["arena", "qwen"],
    "deepseek": ["arena", "qwen"],
}


async def get_effective_session(
    manager: SessionManager, provider: str
) -> Optional[Dict[str, Any]]:
    """Return usable session for ``provider`` or None.

    Resolution order:
      1. Local encrypted cache  (``sessions/<provider>.bin``)
      2. Direct fetch            (``GET /get-session/<provider>``)
      3. Fallback chain          (e.g. arena session used for kimi)
      4. Stale local cache       (graceful degradation, WARNING)
    """
    # 1. local cache
    session = manager.load_session(provider)
    if session and not manager.is_expired(session):
        return session
    # 2. direct fetch from bridge-server
    fresh = await fetch_session_from_server(provider)
    if fresh is not None and (fresh.get("cookies") or provider in {"deepseek", "kimi"}):
        manager.save_session(provider, fresh)
        logger.info("refreshed session for %s from bridge-server", provider)
        return fresh
    # 3. fallback chain (other providers may carry the same cookie blob)
    for fallback in PROVIDER_FALLBACKS.get(provider, []):
        # try local first
        fb_local = manager.load_session(fallback)
        if fb_local and not manager.is_expired(fb_local):
            logger.info(
                "using fallback provider %r session for %s (shared profile)",
                fallback, provider,
            )
            return fb_local
        # then remote
        fb_remote = await fetch_session_from_server(fallback)
        if fb_remote is not None and fb_remote.get("cookies"):
            logger.info(
                "fetched fallback provider %r session for %s (shared profile)",
                fallback, provider,
            )
            # cache under BOTH names so subsequent lookups are O(1)
            manager.save_session(fallback, fb_remote)
            manager.save_session(provider, fb_remote)
            return fb_remote
    # 4. graceful degradation: stale local
    if session:
        logger.warning(
            "using STALE local session for %s (bridge-server unreachable)", provider
        )
        return session
    return None


# ============================================================== Model Cache

def _load_model_cache() -> Dict[str, Any]:
    if not MODEL_CACHE_FILE.exists():
        return {"updated_at": None, "providers": {}}
    try:
        return json.loads(MODEL_CACHE_FILE.read_text())
    except (ValueError, OSError):
        return {"updated_at": None, "providers": {}}


def _atomic_write_json(path: Path, obj: Dict[str, Any]) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(obj, indent=2, ensure_ascii=False))
    tmp.replace(path)


async def update_model_cache(manager: SessionManager) -> Dict[str, Any]:
    """Refresh model.json from each provider's discovery.  Returns updated cache."""
    cache = _load_model_cache()
    providers = cache.get("providers") or {}
    results: Dict[str, Any] = {}

    for provider_name in ("arena", "qwen", "deepseek", "kimi"):
        prev = providers.get(provider_name, {"status": "unknown", "models": []})
        results[provider_name] = {
            "status": "error",
            "last_error": "not attempted",
            "models": prev.get("models", []),
        }
        # Try to get session.  For deepseek, 404 is expected (no login).
        try:
            session = await get_effective_session(manager, provider_name)
        except Exception as exc:
            results[provider_name].update(
                {"status": "error", "last_error": f"session: {exc}"}
            )
            continue

        if session is None:
            results[provider_name].update(
                {"status": "NO_SESSION", "last_error": "no session available"}
            )
            continue

        try:
            pc = ProviderRegistry.get_provider_class_or_404(provider_name)
        except KeyError as exc:
            results[provider_name].update(
                {"status": "error", "last_error": str(exc)}
            )
            continue

        prov = pc(session)
        try:
            if provider_name == "arena":
                models_by_modality: Dict[str, List[str]] = {
                    "text": [], "search": [], "image": [], "code": []
                }
                any_ok = False
                for mod in ("text", "search", "image", "code"):
                    try:
                        ms = await prov.list_models(modality=mod)
                        models_by_modality[mod] = ms
                        if ms:
                            any_ok = True
                    except Exception as exc:
                        logger.warning("arena(%s) failed: %s", mod, exc)
                if any_ok:
                    results[provider_name] = {
                        "status": "ok",
                        "last_error": None,
                        "models": models_by_modality,  # dict per modality
                    }
                else:
                    # keep previous data but flag stale
                    results[provider_name] = {
                        "status": "stale",
                        "last_error": "all modalities returned 0 models",
                        "models": prev.get("models", models_by_modality),
                    }
            else:
                models = await prov.list_models()
                if models:
                    results[provider_name] = {
                        "status": "ok",
                        "last_error": None,
                        "models": models,
                    }
                else:
                    results[provider_name] = {
                        "status": prev.get("status", "empty"),
                        "last_error": "no models discovered",
                        "models": prev.get("models", []),
                    }
        except Exception as exc:
            logger.warning("%s discovery failed: %s", provider_name, exc)
            results[provider_name].update(
                {"status": "stale", "last_error": str(exc)[:300]}
            )
        finally:
            try:
                await prov.cleanup()
            except Exception:
                pass

    out = {
        "updated_at": dt.datetime.now(dt.UTC).replace(tzinfo=None).isoformat() + "Z",
        "providers": results,
    }
    _atomic_write_json(MODEL_CACHE_FILE, out)
    logger.info("model cache updated: %s", {k: v["status"] for k, v in results.items()})
    return out


async def model_cache_loop(manager: SessionManager) -> None:
    while True:
        try:
            await asyncio.sleep(MODEL_CACHE_REFRESH_MINUTES * 60)
            await update_model_cache(manager)
        except asyncio.CancelledError:
            break
        except Exception as exc:
            logger.warning("model_cache_loop iteration failed: %s", exc)


# ===================================================================== FastAPI

@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    fernet = _load_or_create_fernet_key()
    manager = SessionManager(fernet)
    app.state.session_manager = manager
    # Initial cache refresh BEFORE the first request so /v1/models is ready.
    try:
        await update_model_cache(manager)
    except Exception as exc:
        # Don't crash the server if startup discovery fails for any provider —
        # the previous model.json (if any) will be loaded by /v1/models.
        logger.warning("startup cache refresh failed (continuing): %s", exc)
    app.state.cache_task = asyncio.create_task(model_cache_loop(manager))
    try:
        yield
    finally:
        app.state.cache_task.cancel()
        try:
            await app.state.cache_task
        except asyncio.CancelledError:
            pass


app = FastAPI(title="bridge-client", version="1.0.0", lifespan=lifespan)


@app.get("/health")
async def health(request: Request) -> Dict[str, Any]:
    cache = _load_model_cache()
    return {
        "status": "ok",
        "model_cache_updated_at": cache.get("updated_at"),
        "providers": {
            k: v.get("status") for k, v in (cache.get("providers") or {}).items()
        },
    }


@app.get("/v1/models")
async def list_models(request: Request) -> Dict[str, Any]:
    cache = _load_model_cache()
    data: List[Dict[str, Any]] = []
    for prov_name, info in (cache.get("providers") or {}).items():
        models = info.get("models") or []
        if isinstance(models, dict):
            # arena per-modality
            for mod, lst in models.items():
                for m in lst:
                    data.append({
                        "id": f"bridge/arena/{mod}/{m}",
                        "object": "model",
                        "owned_by": "arena",
                        "modality": mod,
                    })
        else:
            for m in models:
                data.append({
                    "id": f"bridge/{prov_name}/{m}",
                    "object": "model",
                    "owned_by": prov_name,
                })
    return {"object": "list", "data": data}


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    model: str
    messages: List[ChatMessage]
    extra_params: Optional[Dict[str, Any]] = None
    stream: bool = False


def _build_openai_response(model: str, content: str) -> Dict[str, Any]:
    return {
        "id": f"chatcmpl-{uuid.uuid4().hex[:24]}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": "stop",
            }
        ],
        "usage": {
            "prompt_tokens": 0,
            "completion_tokens": len(content.split()),
            "total_tokens": len(content.split()),
        },
    }


async def _stream_openai_response(model: str, content: str) -> AsyncIterator[bytes]:
    chunk_id = f"chatcmpl-{uuid.uuid4().hex[:24]}"
    # split into ~20-char chunks to mimic token streaming
    step = 20
    for i in range(0, len(content), step):
        piece = content[i : i + step]
        chunk = {
            "id": chunk_id,
            "object": "chat.completion.chunk",
            "created": int(time.time()),
            "model": model,
            "choices": [
                {
                    "index": 0,
                    "delta": {"content": piece},
                    "finish_reason": None,
                }
            ],
        }
        yield f"data: {json.dumps(chunk)}\n\n".encode()
    final = {
        "id": chunk_id,
        "object": "chat.completion.chunk",
        "created": int(time.time()),
        "model": model,
        "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
    }
    yield f"data: {json.dumps(final)}\n\n".encode()
    yield b"data: [DONE]\n\n"


@app.post("/v1/chat/completions")
async def chat_completions(req: ChatRequest, request: Request) -> Any:
    manager: SessionManager = request.app.state.session_manager

    try:
        parsed = ProviderRegistry.parse(req.model)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    provider_name = parsed["provider"]
    model_id = parsed["model_id"]
    modality = parsed.get("modality")

    try:
        pc = ProviderRegistry.get_provider_class_or_404(provider_name)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    if not req.messages:
        raise HTTPException(status_code=400, detail="messages must not be empty")
    last = req.messages[-1]
    if last.role != "user":
        raise HTTPException(
            status_code=400,
            detail=f"only user-role messages are supported; got {last.role!r}",
        )
    prompt = last.content

    params = dict(req.extra_params or {})
    if modality:
        params["modality"] = modality

    session = await get_effective_session(manager, provider_name)
    if session is None:
        raise HTTPException(
            status_code=503,
            detail=(
                f"AUTH_REQUIRED: bridge-server unreachable and no local session "
                f"available for provider {provider_name!r}"
            ),
        )

    prov = pc(session)
    try:
        content = await prov.execute(model_id, prompt, params)
    except Exception as exc:
        logger.exception("execute failed for %s/%s", provider_name, model_id)
        raise HTTPException(
            status_code=502,
            detail=f"execute failed: {exc}",
        )
    finally:
        try:
            await prov.cleanup()
        except Exception:
            pass

    if req.stream:
        return StreamingResponse(
            _stream_openai_response(req.model, content), media_type="text/event-stream"
        )
    return JSONResponse(_build_openai_response(req.model, content))


# --------------------------------------------------------------------- entry

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=PORT, log_level="info")
