import httpx
import pytest

from app.config import settings
from app.llm import provider as llm_provider


class DummyResponse:
    def __init__(self, payload: dict, status_code: int = 200) -> None:
        self._payload = payload
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(
                "error",
                request=httpx.Request("POST", "https://example.com"),
                response=httpx.Response(self.status_code)
            )

    def json(self) -> dict:
        return self._payload


def test_validate_provider_configuration_requires_openai_key(monkeypatch):
    monkeypatch.setattr(settings, "dev_mode", False)
    monkeypatch.setattr(settings, "llm_provider", "openai")
    monkeypatch.setattr(settings, "embed_provider", "ollama")
    monkeypatch.setattr(settings, "openai_api_key", None)

    with pytest.raises(llm_provider.ConfigurationError):
        llm_provider.validate_provider_configuration()


def test_generate_chat_ollama(monkeypatch):
    monkeypatch.setattr(settings, "llm_provider", "ollama")
    captured: dict[str, object] = {}

    def fake_post(url, json=None, timeout=None, **kwargs):
        captured["url"] = url
        captured["json"] = json
        captured["timeout"] = timeout
        return DummyResponse({"message": {"content": "hello from ollama"}})

    monkeypatch.setattr(llm_provider.httpx, "post", fake_post)
    content = llm_provider.generate_chat(
        messages=[{"role": "user", "content": "Hi"}],
        system_prompt="System"
    )

    assert content == "hello from ollama"
    assert str(captured["url"]).endswith("/api/chat")
    payload = captured["json"]
    assert isinstance(payload, dict)
    assert payload["model"] == settings.ollama_model
    assert payload["messages"][0]["role"] == "system"


def test_generate_chat_openai(monkeypatch):
    monkeypatch.setattr(settings, "llm_provider", "openai")
    monkeypatch.setattr(settings, "dev_mode", False)
    monkeypatch.setattr(settings, "openai_api_key", "sk-test")
    captured: dict[str, object] = {}

    def fake_post(url, json=None, headers=None, timeout=None, **kwargs):
        captured["url"] = url
        captured["json"] = json
        captured["headers"] = headers
        captured["timeout"] = timeout
        return DummyResponse({"choices": [{"message": {"content": "hello from openai"}}]})

    monkeypatch.setattr(llm_provider.httpx, "post", fake_post)
    content = llm_provider.generate_chat(
        messages=[{"role": "user", "content": "Hi"}],
        system_prompt="System"
    )

    assert content == "hello from openai"
    assert str(captured["url"]).endswith("/chat/completions")
    headers = captured["headers"]
    assert isinstance(headers, dict)
    assert headers["Authorization"] == "Bearer sk-test"


def test_embed_texts_ollama_retries(monkeypatch):
    monkeypatch.setattr(settings, "embed_provider", "ollama")
    calls = {"count": 0}

    def fake_post(url, json=None, timeout=None, **kwargs):
        calls["count"] += 1
        if calls["count"] < 3:
            raise httpx.ReadTimeout("timeout")
        return DummyResponse({"embedding": [0.1, 0.2]})

    monkeypatch.setattr(llm_provider.httpx, "post", fake_post)
    vectors = llm_provider.embed_texts(["hello"])

    assert vectors == [[0.1, 0.2]]
    assert calls["count"] == 3


def test_embed_texts_openai(monkeypatch):
    monkeypatch.setattr(settings, "embed_provider", "openai")
    monkeypatch.setattr(settings, "dev_mode", False)
    monkeypatch.setattr(settings, "openai_api_key", "sk-test")

    def fake_post(url, json=None, headers=None, timeout=None, **kwargs):
        return DummyResponse(
            {
                "data": [
                    {"index": 1, "embedding": [0.3, 0.4]},
                    {"index": 0, "embedding": [0.1, 0.2]}
                ]
            }
        )

    monkeypatch.setattr(llm_provider.httpx, "post", fake_post)
    vectors = llm_provider.embed_texts(["first", "second"])

    assert vectors == [[0.1, 0.2], [0.3, 0.4]]


def test_probe_openai_connectivity_short_circuits_without_key(monkeypatch):
    monkeypatch.setattr(settings, "openai_api_key", None)

    def fail_get(*args, **kwargs):
        raise AssertionError("openai probe should not call network without key")

    monkeypatch.setattr(llm_provider.httpx, "get", fail_get)
    assert llm_provider.probe_openai_connectivity() is False


def test_generate_chat_mock_mentions_context(monkeypatch):
    monkeypatch.setattr(settings, "llm_provider", "mock")
    monkeypatch.setattr(settings, "embedding_dim", 8)
    content = llm_provider.generate_chat(
        messages=[{"role": "user", "content": "Hello mock"}],
        retrieved_chunks_count=2
    )
    assert "Hello mock" in content
    assert "Retrieved context used: 2 chunks." in content


def test_embed_texts_mock_is_deterministic(monkeypatch):
    monkeypatch.setattr(settings, "embed_provider", "mock")
    monkeypatch.setattr(settings, "embedding_dim", 5)
    first = llm_provider.embed_texts(["same input"])[0]
    second = llm_provider.embed_texts(["same input"])[0]
    assert len(first) == 5
    assert first == second
