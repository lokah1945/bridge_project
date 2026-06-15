"""Unit tests for gateway helpers that do not require a browser."""
import pytest
from client.gateway import parse_model_id, build_model_id, format_messages, _estimate_tokens
from client.gateway import ChatMessage


def test_parse_model_id_arena():
    provider, modality, model_id = parse_model_id("bridge/arena/text/gpt-4o")
    assert provider == "arena"
    assert modality == "text"
    assert model_id == "gpt-4o"


def test_parse_model_id_qwen():
    provider, modality, model_id = parse_model_id("bridge/qwen/qwen-max")
    assert provider == "qwen"
    assert modality is None
    assert model_id == "qwen-max"


def test_parse_model_id_invalid():
    with pytest.raises(ValueError):
        parse_model_id("openai/gpt-4o")
    with pytest.raises(ValueError):
        parse_model_id("bridge/arena")


def test_build_model_id():
    assert build_model_id("arena", "gpt-4o", "text") == "bridge/arena/text/gpt-4o"
    assert build_model_id("qwen", "qwen-max") == "bridge/qwen/qwen-max"


def test_format_messages():
    messages = [
        ChatMessage(role="system", content="You are a helpful assistant."),
        ChatMessage(role="user", content="Hello!"),
        ChatMessage(role="assistant", content="Hi there!"),
    ]
    result = format_messages(messages)
    assert "System: You are a helpful assistant." in result
    assert "User: Hello!" in result
    assert "Assistant: Hi there!" in result


def test_estimate_tokens():
    assert _estimate_tokens("") == 1
    assert _estimate_tokens("hello") == 1
    assert _estimate_tokens("a" * 40) == 10
