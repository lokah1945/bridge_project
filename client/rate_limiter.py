"""Simple in-memory token-bucket rate limiter per API key / IP."""
import time
from typing import Dict, Optional

from client.config import settings


class RateLimiter:
    """Token bucket rate limiter."""

    def __init__(self, rate_per_min: int):
        self.rate_per_min = max(1, rate_per_min)
        self._buckets: Dict[str, Dict[str, float]] = {}

    def _reset(self, key: str) -> None:
        self._buckets[key] = {"tokens": float(self.rate_per_min), "last": time.time()}

    def is_allowed(self, key: str) -> bool:
        if self.rate_per_min <= 0:
            return True

        if key not in self._buckets:
            self._reset(key)

        bucket = self._buckets[key]
        now = time.time()
        elapsed = now - bucket["last"]
        bucket["tokens"] = min(
            float(self.rate_per_min),
            bucket["tokens"] + elapsed * (self.rate_per_min / 60.0),
        )
        bucket["last"] = now

        if bucket["tokens"] >= 1.0:
            bucket["tokens"] -= 1.0
            return True
        return False

    def reset_key(self, key: str) -> None:
        self._buckets.pop(key, None)


rate_limiter = RateLimiter(settings.rate_limit_per_min)


def get_limit_key(credentials: Optional[object], request: Optional[object]) -> str:
    """Derive rate-limit key from API key or client IP."""
    if credentials and credentials.credentials:
        return f"key:{credentials.credentials}"
    if request and hasattr(request, "client") and request.client:
        return f"ip:{request.client.host}"
    return "ip:unknown"
