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
from client.logging_config import logger
from client.model_cache import cache_loop, get_cached_models, update_cache
from client.rate_limiter import get_limit_key, rate_limiter
from client.session_manager import SessionManager
from registry import registry
from providers.arena import ArenaProvider
from providers.qwen import QwenProvider
from providers.deepseek import DeepSeekProvider

registry.register("arena", ArenaProvider)
registry.register("qwen", QwenProvider)
registry.register("deepseek", DeepSeekProvider)

security = HTTPBearer(auto_error=False)

# Global concurrency limiter for browser automation. If the limit is reached,
# requests wait in the queue with a configurable timeout instead of being rejected.
_request_semaphore = asyncio.Semaphore(settings.concurrency_limit)

# Metrics counters (in-memory; Prometheus optional extension can scrape these).
_metrics = {
    "requests_total": 0,
    "errors_total": 0,
    "provider_latency_seconds": {},
}


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


def _sanitize_text(text: str) -> str:
    """Sanitize text before injecting into a textarea/input."""
    # Remove control characters except newlines (some providers support them).
    sanitized = "".join(ch for ch in text if ch == "\n" or (ord(ch) >= 32 and ord(ch) != 127))
    return sanitized


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


def _check_rate_limit(credentials: Optional[HTTPAuthorizationCredentials], request: Request) -> None:
    key = get_limit_key(credentials, request)
    if not rate_limiter.is_allowed(key):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Rate limit exceeded. Slow down or increase RATE_LIMIT_PER_MIN.",
        )


def _validate_model_against_cache(model: str) -> None:
    """Fast-fail if model ID is not in the cached model list."""
    models = get_cached_models()
    if not models:
        return  # Allow if cache is empty; actual provider will fail later if invalid.
    valid_ids = {m.get("id") for m in models}
    if model not in valid_ids:
        # Also accept if the provider part is valid but exact model not cached.
        try:
            provider, _, _ = parse_model_id(model)
            if not any(m.get("id", "").startswith(f"bridge/{provider}/") for m in models):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Unknown provider in model ID: {model}",
                )
        except ValueError as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(e),
            ) from e


def _to_http_error(exc: Exception) -> ProviderError:
    """Classify automation errors into HTTP status codes."""
    msg = str(exc).lower()
    if isinstance(exc, TimeoutError):
        return ProviderError(status.HTTP_504_GATEWAY_TIMEOUT, f"Provider timeout: {exc}")
    if "login" in msg or "unauthorized" in msg or "authentication" in msg:
        return ProviderError(
            status.HTTP_424_FAILED_DEPENDENCY,
            "Session expired or provider requires login. Please refresh the bridge-server session.",
        )
    if "bridge-server" in msg or "unreachable" in msg or "session" in msg:
        return ProviderError(
            status.HTTP_424_FAILED_DEPENDENCY,
            str(exc),
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

    # Warn if API key is empty and gateway is exposed to the network.
    if not settings.api_key and settings.host == "0.0.0.0":
        logger.warning(
            "API_KEY is not set and gateway is listening on 0.0.0.0. "
            "Set API_KEY in .env to prevent unauthorized access."
        )

    try:
        asyncio.create_task(update_cache(session_manager))
        asyncio.create_task(cache_loop(session_manager))
        asyncio.create_task(session_manager.refresh_loop())
    except Exception as e:
        logger.error(f"[Gateway] initial background setup failed: {e}")
    yield
    await browser_manager.shutdown()


app = FastAPI(title="Bridge-Client OpenAI Gateway", lifespan=_lifespan)


@app.get("/health")
async def health():
    """Extended health check with session and cache status."""
    session_manager = SessionManager()
    providers = ["arena", "qwen", "deepseek"]
    provider_status = {}
    for provider in providers:
        session = session_manager.load(provider)
        provider_status[provider] = {
            "cached": session is not None,
            "expired": session is None and session_manager._file_path(provider).exists(),
            "stale": session_manager.is_stale(provider) if session else None,
            "last_refresh": session_manager._last_refresh.get(provider, None),
        }

    cache_info = {}
    try:
        import json as _json
        with open(settings.model_cache_file, "r") as f:
            cache_data = _json.load(f)
        cache_info = {
            "exists": True,
            "last_updated": cache_data.get("last_updated"),
            "model_count": len(cache_data.get("models", [])),
        }
    except Exception:
        cache_info = {"exists": False, "last_updated": None, "model_count": 0}

    return {
        "status": "ok",
        "bridge_server_url": settings.bridge_server_url,
        "model_cache_file": str(settings.model_cache_file),
        "provider_status": provider_status,
        "cache": cache_info,
        "metrics": {
            "requests_total": _metrics["requests_total"],
            "errors_total": _metrics["errors_total"],
            "concurrency_limit": settings.concurrency_limit,
        },
    }


@app.get("/metrics")
async def metrics():
    """Lightweight Prometheus-compatible metrics endpoint."""
    lines = [
        "# HELP bridge_client_requests_total Total requests",
        "# TYPE bridge_client_requests_total counter",
        f"bridge_client_requests_total { _metrics['requests_total']}",
        "# HELP bridge_client_errors_total Total errors",
        "# TYPE bridge_client_errors_total counter",
        f"bridge_client_errors_total {_metrics['errors_total']}",
    ]
    for provider, latencies in _metrics["provider_latency_seconds"].items():
        lines.append(f"# HELP bridge_client_provider_latency_seconds_{provider} Provider latency")
        lines.append(f"# TYPE bridge_client_provider_latency_seconds_{provider} gauge")
        lines.append(f"bridge_client_provider_latency_seconds_{provider} {latencies}")
    return "\n".join(lines)


@app.get("/v1/models")
async def list_models(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
):
    _verify_api_key(credentials)
    _check_rate_limit(credentials, request)
    models = get_cached_models()
    if not models:
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
    _check_rate_limit(credentials, request)
    _metrics["requests_total"] += 1

    try:
        body = await request.json()
        req = ChatCompletionRequest(**body)
    except (json.JSONDecodeError, ValidationError) as e:
        _metrics["errors_total"] += 1
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Invalid request body: {e}")

    try:
        provider_name, modality, model_id = parse_model_id(req.model)
    except ValueError as e:
        _metrics["errors_total"] += 1
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

    _validate_model_against_cache(req.model)

    provider_class = registry.get_provider_class(provider_name)
    if not provider_class:
        _metrics["errors_total"] += 1
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Provider '{provider_name}' not registered",
        )

    extra_params = dict(req.extra_params)
    if provider_name == "arena" and modality:
        extra_params["modality"] = modality

    prompt = _sanitize_text(format_messages(req.messages))
    if not prompt:
        _metrics["errors_total"] += 1
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No prompt content provided")

    if len(prompt) > settings.max_prompt_chars:
        _metrics["errors_total"] += 1
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"Prompt exceeds MAX_PROMPT_CHARS limit ({settings.max_prompt_chars})",
        )

    session_manager = SessionManager()
    try:
        session = await session_manager.get_effective_session(provider_name)
    except Exception as e:
        _metrics["errors_total"] += 1
        err = _to_http_error(e)
        raise HTTPException(status_code=err.status_code, detail=err.detail)

    start_time = time.time()
    try:
        # Wait for the semaphore with a timeout to avoid queueing forever.
        acquired = await asyncio.wait_for(
            _request_semaphore.acquire(), timeout=30.0
        )
    except asyncio.TimeoutError:
        _metrics["errors_total"] += 1
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Too many concurrent requests. Try again later.",
        )

    response_text = ""
    try:
        provider = provider_class(session)
        try:
            response_text = await provider.execute(model_id, prompt, extra_params)
        except Exception as e:
            _metrics["errors_total"] += 1
            logger.warning(f"Provider execution failed for {provider_name}/{model_id}: {e}")
            err = _to_http_error(e)
            raise HTTPException(status_code=err.status_code, detail=err.detail)
        finally:
            try:
                await provider.cleanup()
            except Exception as cleanup_err:
                logger.warning(f"Provider cleanup failed: {cleanup_err}")
    finally:
        _request_semaphore.release()

    elapsed = time.time() - start_time
    _metrics["provider_latency_seconds"][provider_name] = _metrics["provider_latency_seconds"].get(provider_name, 0) + elapsed

    if not isinstance(response_text, str):
        _metrics["errors_total"] += 1
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Provider returned non-string response",
        )

    created = int(time.time())
    completion_id = f"chatcmpl-{uuid.uuid4().hex[:12]}"

    if req.stream:
        async def stream_generator() -> AsyncIterator[str]:
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
