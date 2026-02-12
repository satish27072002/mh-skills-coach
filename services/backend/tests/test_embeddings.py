import pytest

from app.embeddings import get_embedding
from app.llm.provider import ProviderError


def test_get_embedding_uses_provider(monkeypatch):
    monkeypatch.setattr("app.embeddings.embed_texts", lambda texts: [[0.1, 0.2]])

    embedding = get_embedding("hello")

    assert embedding == [0.1, 0.2]


def test_get_embedding_raises_clean_error(monkeypatch):
    monkeypatch.setattr(
        "app.embeddings.embed_texts",
        lambda texts: (_ for _ in ()).throw(ProviderError("provider down"))
    )

    with pytest.raises(RuntimeError, match="provider down"):
        get_embedding("hello")
