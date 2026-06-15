"""Integration tests for the FastAPI gateway using TestClient."""
import json
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from client.gateway import app
from client import model_cache


@pytest.fixture
def client():
    return TestClient(app)


def test_health(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_models_empty_cache(client, tmp_path, monkeypatch):
    # Point to a non-existent cache so the endpoint tries to refresh.
    monkeypatch.setattr("client.model_cache.MODEL_CACHE_FILE", tmp_path / "empty.json")
    # Patch update_cache to avoid browser use.
    with patch("client.gateway.update_cache") as mock_update:
        mock_update.return_value = {"models": []}
        resp = client.get("/v1/models")
        assert resp.status_code == 503 or resp.status_code == 200


def test_chat_completions_non_stream(client):
    with patch("client.gateway.SessionManager") as MockSM, \
         patch("client.gateway.registry.get_provider_class") as mock_get:

        MockSM.return_value.get_effective_session = AsyncMock(
            return_value={"cookies": [], "user_agent": "UA"}
        )
        mock_provider = AsyncMock()
        mock_provider.execute = AsyncMock(return_value="Hello from test provider")
        mock_provider.cleanup = AsyncMock()
        mock_get.return_value = lambda session: mock_provider

        resp = client.post(
            "/v1/chat/completions",
            json={
                "model": "bridge/qwen/qwen-max",
                "messages": [{"role": "user", "content": "Hi"}],
                "stream": False,
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["object"] == "chat.completion"
        assert data["choices"][0]["message"]["content"] == "Hello from test provider"
        assert data["choices"][0]["finish_reason"] == "stop"
        assert "usage" in data


def test_chat_completions_stream(client):
    with patch("client.gateway.SessionManager") as MockSM, \
         patch("client.gateway.registry.get_provider_class") as mock_get:

        MockSM.return_value.get_effective_session = AsyncMock(
            return_value={"cookies": [], "user_agent": "UA"}
        )
        mock_provider = AsyncMock()
        mock_provider.execute = AsyncMock(return_value="Hello world")
        mock_provider.cleanup = AsyncMock()
        mock_get.return_value = lambda session: mock_provider

        resp = client.post(
            "/v1/chat/completions",
            json={
                "model": "bridge/qwen/qwen-max",
                "messages": [{"role": "user", "content": "Hi"}],
                "stream": True,
            },
        )
        assert resp.status_code == 200
        lines = [line for line in resp.iter_lines()]
        text = "\n".join(lines)
        assert "data: [DONE]" in text
        assert '"finish_reason": "stop"' in text


def test_chat_completions_invalid_model(client):
    resp = client.post(
        "/v1/chat/completions",
        json={"model": "openai/gpt-4", "messages": [{"role": "user", "content": "Hi"}]},
    )
    assert resp.status_code == 400
