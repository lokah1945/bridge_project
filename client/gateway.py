"""OpenAI-compatible FastAPI gateway for bridge-client."""
import asyncio
import json
import time
import uuid
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator, Dict, List, Optional, Tuple

from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field, ValidationError

from client import browser_manager
from client.config import settings
from client.model_cache import cache_loop, get_cached_models, update_cache
from client.session_manager import SessionManager
from registry import registry
from providers.arena import ArenaProvider
from providers.qwen import QwenProvider
from providers.deepseek import DeepSeekProvider

registry.register("arena", ArenaProvider)
registry.register("qwen", QwenProvider)
registry.register("deepseek", DeepSeekProvider)

security = HTTPBearer(auto_error=False)

# Global semaphore to limit concurrent browser automation requests.
_request_semaphore = asyncio.Semaphore(settings.concurrency_limit)


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatCompletionRequest(BaseModel):
    model: str
    messages: List[ChatMessage]
    stream: bool = False
    extra_params: Dict[str, Any] = Field(default_factory=dict)


class ProviderError(Exception):
    def __init__(self, status_code: int, detail: str):
        self.status_code = status_code
        self.detail = detail


def parse_model_id(model: str) -> Tuple[str, Optional[str], str]:
    """Parse bridge/<provider>/<modality?>/<model_id> into components.

    Returns: (provider_name, modality_or_None, model_id)
    """
    if not model.startswith("bridge/"):
        raise ValueError("Model ID must start with 'bridge/'")

    parts = model.split("/")
    if len(parts) < 3:
        raise ValueError("Model ID must be bridge/<provider>/<model_id>")

    provider = parts[1].lower()
    if provider == "arena":
        if len(parts) < 4:
            raise ValueError("Arena model ID must be bridge/arena/<modality>/<model_id>")
        return provider, parts[2], parts[3]

    # For other providers, modality is optional and defaults to None.
    modality = parts[2] if len(parts) > 3 else None
    return provider, modality, parts[2]


def build_model_id(provider: str, model_id: str, modality: Optional[str] = None) -> str:
    if provider == "arena" and modality:
        return f"bridge/arena/{modality}/{model_id}"
    return f"bridge/{provider}/{model_id}"


def format_messages(messages: List[ChatMessage]) -> str:
    """Convert OpenAI messages[] into a single prompt string for providers."""
    parts = []
    for msg in messages:
        if not msg.content:
            continue
        if msg.role == "system":
            parts.append(f"System: {msg.content}")
        elif msg.role == "user":
            parts.append(f"User: {msg.content}")
        elif msg.role == "assistant":
            parts.append(f"Assistant: {msg.content}")
        else:
            parts.append(f"{msg.role}: {msg.content}")
    return "\n\n".join(parts)


def _estimate_tokens(text: str) -> int:
    """Rough token estimate for usage field."""
    return max(1, len(text) // 4)


def _verify_api_key(credentials: Optional[HTTPAuthorizationCredentials]) -> None:
    if not settings.api_key:
        return
    if credentials is None or credentials.credentials != settings.api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing API key",
        )


def _to_http_error(exc: Exception) -> ProviderError:
    """Classify automation errors into HTTP status codes."""
    msg = str(exc).lower()
    if isinstance(exc, TimeoutError):
        return ProviderError(status.HTTP_504_GATEWAY_TIMEOUT, f"Provider timeout: {exc}")
    if "login" in msg or "unauthorized" in msg or "authentication" in msg or "session" in msg:
        return ProviderError(
            status.HTTP_424_FAILED_DEPENDENCY,
            "Session expired or provider requires login. Please refresh the bridge-server session.",
        )
    if "rate" in msg or "limit" in msg or "too many" in msg:
        return ProviderError(status.HTTP_429_TOO_MANY_REQUESTS, f"Provider rate limit: {exc}")
    if "selector" in msg or "not found" in msg or "textarea" in msg:
        return ProviderError(status.HTTP_502_BAD_GATEWAY, f"Provider UI changed or selector missing: {exc}")
    return ProviderError(status.HTTP_502_BAD_GATEWAY, f"Provider automation error: {exc}")


@asynccontextmanager
async def _lifespan(app: FastAPI):
    """Startup: warm session cache and start background refresh; shutdown: close browser."""
    session_manager = SessionManager()
    try:
        # Initial model discovery on startup.
        asyncio.create_task(update_cache(session_manager))
        # Background periodic refresh.
        asyncio.create_task(cache_loop(session_manager))
    except Exception as e:
        print(f"[Gateway] initial cache setup failed: {e}")
    yield
    await browser_manager.shutdown()


app = FastAPI(title="Bridge-Client OpenAI Gateway", lifespan=_lifespan)


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "bridge_server_url": settings.bridge_server_url,
        "model_cache_file": str(settings.model_cache_file),
    }


@app.get("/v1/models")
async def list_models(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
):
    _verify_api_key(credentials)
    models = get_cached_models()
    if not models:
        # If cache is empty, try to refresh synchronously.
        try:
            await update_cache()
            models = get_cached_models()
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=f"Model cache not available: {e}",
            )
    return {"object": "list", "data": models}


@app.post("/v1/chat/completions")
async def chat_completions(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
):
    _verify_api_key(credentials)

    try:
        body = await request.json()
        req = ChatCompletionRequest(**body)
    except (json.JSONDecodeError, ValidationError) as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Invalid request body: {e}")

    try:
        provider_name, modality, model_id = parse_model_id(req.model)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

    provider_class = registry.get_provider_class(provider_name)
    if not provider_class:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Provider '{provider_name}' not registered",
        )

    extra_params = dict(req.extra_params)
    if provider_name == "arena" and modality:
        extra_params["modality"] = modality

    prompt = format_messages(req.messages)
    if not prompt:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No prompt content provided")

    session_manager = SessionManager()
    try:
        session = await session_manager.get_effective_session(provider_name)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_424_FAILED_DEPENDENCY,
            detail=f"Unable to obtain session: {e}",
        )

    async with _request_semaphore:
        provider = provider_class(session)
        try:
            response_text = await provider.execute(model_id, prompt, extra_params)
        except Exception as e:
            err = _to_http_error(e)
            raise HTTPException(status_code=err.status_code, detail=err.detail)
        finally:
            try:
                await provider.cleanup()
            except Exception:
                pass

    if not isinstance(response_text, str):
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Provider returned non-string response",
        )

    created = int(time.time())
    completion_id = f"chatcmpl-{uuid.uuid4().hex[:12]}"

    if req.stream:
        async def stream_generator() -> AsyncIterator[str]:
            # Yield the full response in word-sized chunks to simulate streaming.
            words = response_text.split(" ")
            for i, word in enumerate(words):
                chunk = word + (" " if i < len(words) - 1 else "")
                data = {
                    "id": completion_id,
                    "object": "chat.completion.chunk",
                    "created": created,
                    "model": req.model,
                    "choices": [
                        {
                            "index": 0,
                            "delta": {"content": chunk},
                            "finish_reason": None,
                        }
                    ],
                }
                yield f"data: {json.dumps(data)}\n\n"
                await asyncio.sleep(0.01)

            # Final chunk with finish_reason.
            yield f"data: {json.dumps({'id': completion_id, 'object': 'chat.completion.chunk', 'created': created, 'model': req.model, 'choices': [{'index': 0, 'delta': {}, 'finish_reason': 'stop'}]})}\n\n"
            yield "data: [DONE]\n\n"

        return StreamingResponse(stream_generator(), media_type="text/event-stream")

    return {
        "id": completion_id,
        "object": "chat.completion",
        "created": created,
        "model": req.model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": response_text},
                "finish_reason": "stop",
            }
        ],
        "usage": {
            "prompt_tokens": _estimate_tokens(prompt),
            "completion_tokens": _estimate_tokens(response_text),
            "total_tokens": _estimate_tokens(prompt) + _estimate_tokens(response_text),
        },
    }
