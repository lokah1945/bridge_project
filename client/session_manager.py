"""Session Manager: fetch, encrypt, cache, and refresh bridge-server sessions."""
import asyncio
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Optional

import httpx
from cryptography.fernet import Fernet

from client.config import settings, SESSION_DIR
from client.logging_config import logger


class SessionManager:
    """Handles encrypted local storage of provider sessions fetched from the bridge-server."""

    def __init__(self, session_dir: Optional[Path] = None, encryption_key: Optional[str] = None):
        self.session_dir = session_dir or SESSION_DIR
        self.key = (encryption_key or settings.encryption_key or "").strip()
        if not self.key:
            raise RuntimeError(
                "ENCRYPTION_KEY is not set. Generate a valid Fernet key and add it to .env."
            )
        self.cipher = Fernet(self.key.encode())
        self.session_dir.mkdir(parents=True, exist_ok=True)
        # In-memory tracking of last-known session freshness per provider.
        self._last_refresh: Dict[str, datetime] = {}

    def _file_path(self, provider: str) -> Path:
        return self.session_dir / f"{provider}.enc"

    def save(self, provider: str, data: Dict[str, Any]) -> None:
        """Encrypt and persist session data."""
        if "_saved_at" not in data:
            data["_saved_at"] = datetime.now().isoformat()
        payload = json.dumps(data).encode("utf-8")
        encrypted = self.cipher.encrypt(payload)
        self._file_path(provider).write_bytes(encrypted)
        self._last_refresh[provider] = datetime.now()

    def load(self, provider: str) -> Optional[Dict[str, Any]]:
        """Load and decrypt session data, returning None if invalid/expired."""
        path = self._file_path(provider)
        if not path.exists():
            return None
        try:
            encrypted = path.read_bytes()
            decrypted = self.cipher.decrypt(encrypted)
            data = json.loads(decrypted)
            if self.is_expired(data):
                return None
            self._last_refresh[provider] = datetime.fromisoformat(data["_saved_at"])
            return data
        except Exception as e:
            if settings.debug:
                logger.warning(f"SessionManager failed to load {provider}: {e}")
            return None

    def is_expired(self, data: Dict[str, Any]) -> bool:
        """Check if the session is older than SESSION_TTL_HOURS."""
        saved_at = data.get("_saved_at")
        if not saved_at:
            return True
        try:
            saved = datetime.fromisoformat(saved_at)
        except ValueError:
            return True
        ttl = timedelta(hours=settings.session_ttl_hours)
        return datetime.now() > saved + ttl

    def is_stale(self, provider: str) -> bool:
        """Check if local session is approaching refresh window."""
        data = self.load(provider)
        if not data:
            return True
        saved_at = data.get("_saved_at")
        if not saved_at:
            return True
        try:
            saved = datetime.fromisoformat(saved_at)
        except ValueError:
            return True
        # Refresh proactively after half of TTL to avoid request-time refresh.
        refresh_after = timedelta(hours=settings.session_ttl_hours / 2)
        return datetime.now() > saved + refresh_after

    def clear(self, provider: Optional[str] = None) -> None:
        """Remove cached session(s)."""
        if provider:
            path = self._file_path(provider)
            if path.exists():
                path.unlink()
            self._last_refresh.pop(provider, None)
        else:
            for path in self.session_dir.glob("*.enc"):
                path.unlink()
            self._last_refresh.clear()

    async def fetch(self, provider: str) -> Dict[str, Any]:
        """Fetch fresh session from bridge-server with retries and exponential backoff."""
        last_error: Optional[Exception] = None
        max_retries = 3
        for attempt in range(1, max_retries + 1):
            try:
                async with httpx.AsyncClient() as client:
                    resp = await client.get(
                        f"{settings.bridge_server_url}/get-session/{provider}",
                        timeout=10.0,
                    )
                    if resp.status_code == 200:
                        data = resp.json()
                        self.save(provider, data)
                        return data
                    if resp.status_code in (404, 503):
                        raise RuntimeError(
                            f"Bridge-server returned {resp.status_code} for provider '{provider}'"
                        )
                    raise RuntimeError(
                        f"Bridge-server returned {resp.status_code} for provider '{provider}'"
                    )
            except Exception as e:
                last_error = e
                if settings.debug:
                    logger.warning(f"Session fetch attempt {attempt} failed for {provider}: {e}")
                if attempt < max_retries:
                    await asyncio.sleep(2 ** attempt)  # 2, 4, 8 seconds
        raise RuntimeError(
            f"Unable to fetch session for '{provider}' after {max_retries} attempts: {last_error}"
        ) from last_error

    async def get_effective_session(self, provider: str) -> Dict[str, Any]:
        """Return valid session: cached if fresh, otherwise fetch from server."""
        session = self.load(provider)
        if session is not None:
            return session

        try:
            return await self.fetch(provider)
        except Exception as e:
            logger.warning(f"Session fetch failed for {provider}: {e}")
            # Fallback: return stale cache if server is unreachable, but only if it exists.
            path = self._file_path(provider)
            if path.exists():
                try:
                    encrypted = path.read_bytes()
                    data = json.loads(self.cipher.decrypt(encrypted))
                    data["_stale"] = True
                    return data
                except Exception:
                    pass
            raise RuntimeError(
                f"Unable to obtain session for '{provider}': bridge-server unreachable and no valid cache"
            ) from e

    async def refresh_if_stale(self, provider: str) -> None:
        """Proactive refresh before TTL. Returns silently; logs on failure."""
        if self.is_stale(provider):
            try:
                await self.fetch(provider)
                logger.info(f"Proactively refreshed session for {provider}")
            except Exception as e:
                logger.warning(f"Proactive session refresh failed for {provider}: {e}")

    async def refresh_loop(self, providers=None) -> None:
        """Background loop that refreshes sessions periodically."""
        providers = providers or ["arena", "qwen", "deepseek"]
        while True:
            for provider in providers:
                try:
                    await self.refresh_if_stale(provider)
                except Exception as e:
                    logger.warning(f"Session refresh loop error for {provider}: {e}")
            await asyncio.sleep(settings.session_refresh_interval_min * 60)
