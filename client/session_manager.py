"""Session Manager: fetch, encrypt, cache, and refresh bridge-server sessions."""
import json
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Optional

import httpx
from cryptography.fernet import Fernet

from client.config import settings, SESSION_DIR


class SessionManager:
    """Handles encrypted local storage of provider sessions fetched from the bridge-server."""

    def __init__(self, session_dir: Optional[Path] = None, encryption_key: Optional[str] = None):
        self.session_dir = session_dir or SESSION_DIR
        self.key = (encryption_key or settings.encryption_key or "").strip()
        if not self.key:
            self.key = Fernet.generate_key().decode()
            print(
                "[SessionManager] WARNING: ENCRYPTION_KEY not set. A new key was generated. "
                "Persist it in your .env to avoid re-authentication on restart."
            )
        try:
            self.cipher = Fernet(self.key.encode())
        except ValueError:
            print(
                "[SessionManager] WARNING: ENCRYPTION_KEY is invalid. Generating a new key. "
                "A valid Fernet key is 32 url-safe base64-encoded bytes."
            )
            self.key = Fernet.generate_key().decode()
            self.cipher = Fernet(self.key.encode())
        self.session_dir.mkdir(parents=True, exist_ok=True)

    def _file_path(self, provider: str) -> Path:
        return self.session_dir / f"{provider}.enc"

    def save(self, provider: str, data: Dict[str, Any]) -> None:
        """Encrypt and persist session data."""
        if "_saved_at" not in data:
            data["_saved_at"] = datetime.now().isoformat()
        payload = json.dumps(data).encode("utf-8")
        encrypted = self.cipher.encrypt(payload)
        self._file_path(provider).write_bytes(encrypted)

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
            return data
        except Exception as e:
            if settings.debug:
                print(f"[SessionManager] Failed to load {provider}: {e}")
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

    def clear(self, provider: Optional[str] = None) -> None:
        """Remove cached session(s)."""
        if provider:
            path = self._file_path(provider)
            if path.exists():
                path.unlink()
        else:
            for path in self.session_dir.glob("*.enc"):
                path.unlink()

    async def fetch(self, provider: str) -> Dict[str, Any]:
        """Fetch fresh session from bridge-server."""
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{settings.bridge_server_url}/get-session/{provider}",
                timeout=10.0,
            )
            if resp.status_code != 200:
                raise RuntimeError(
                    f"Bridge-server returned {resp.status_code} for provider '{provider}'"
                )
            data = resp.json()
            self.save(provider, data)
            return data

    async def get_effective_session(self, provider: str) -> Dict[str, Any]:
        """Return valid session: cached if fresh, otherwise fetch from server."""
        session = self.load(provider)
        if session is not None:
            return session

        try:
            return await self.fetch(provider)
        except Exception as e:
            if settings.debug:
                print(f"[SessionManager] Fetch failed for {provider}: {e}")
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
            raise RuntimeError(f"Unable to obtain session for '{provider}': {e}") from e
