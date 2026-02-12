import pytest

from app.config import settings
from app.embed_dimension import (
    get_active_embedding_dim,
    get_cached_embedding_dim,
    reset_detected_embedding_dim,
)


def setup_function():
    reset_detected_embedding_dim()


def test_detects_openai_dimension_when_unset(monkeypatch):
    monkeypatch.setattr(settings, "embed_provider", "openai")
    monkeypatch.setattr(settings, "openai_embed_model", "text-embedding-3-small")
    monkeypatch.setattr(settings, "embedding_dim", None)
    calls = {"count": 0}

    def fake_embed(_texts):
        calls["count"] += 1
        return [[0.0] * 1536]

    dim = get_active_embedding_dim(embed_fn=fake_embed)
    dim_second = get_active_embedding_dim(embed_fn=fake_embed)

    assert dim == 1536
    assert dim_second == 1536
    assert calls["count"] == 1
    assert get_cached_embedding_dim() == 1536


def test_raises_when_configured_dim_mismatches_known_openai_model(monkeypatch):
    monkeypatch.setattr(settings, "embed_provider", "openai")
    monkeypatch.setattr(settings, "openai_embed_model", "text-embedding-3-small")
    monkeypatch.setattr(settings, "embedding_dim", 768)

    with pytest.raises(RuntimeError, match="does not match OPENAI_EMBED_MODEL"):
        get_active_embedding_dim()


def test_ollama_defaults_to_legacy_dim_when_unset(monkeypatch):
    monkeypatch.setattr(settings, "embed_provider", "ollama")
    monkeypatch.setattr(settings, "embedding_dim", None)

    dim = get_active_embedding_dim()

    assert dim == 768
    assert get_cached_embedding_dim() == 768
