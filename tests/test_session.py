"""Unit tests for SessionManager encryption roundtrip."""
import pytest

from client.session_manager import SessionManager


def test_session_encryption_roundtrip(tmp_path):
    key = "test-key-" + "x" * 40  # Fernet requires 32 url-safe base64 bytes
    from cryptography.fernet import Fernet
    valid_key = Fernet.generate_key().decode()

    sm = SessionManager(session_dir=tmp_path, encryption_key=valid_key)
    data = {"cookies": [{"name": "session", "value": "abc123"}], "user_agent": "UA"}
    sm.save("arena", data)

    loaded = sm.load("arena")
    assert loaded is not None
    assert loaded["cookies"] == data["cookies"]
    assert loaded["user_agent"] == data["user_agent"]


def test_session_expired(tmp_path):
    from datetime import datetime, timedelta
    from cryptography.fernet import Fernet

    valid_key = Fernet.generate_key().decode()
    sm = SessionManager(session_dir=tmp_path, encryption_key=valid_key)
    old = {"_saved_at": (datetime.now() - timedelta(days=2)).isoformat()}
    sm.save("arena", old)
    assert sm.load("arena") is None
