from __future__ import annotations

from typing import Callable

from .config import settings
from .llm.provider import embed_texts


DEFAULT_OLLAMA_EMBED_DIM = 768
DEFAULT_MOCK_EMBED_DIM = 1536
OPENAI_MODEL_DIMENSIONS: dict[str, int] = {
    "text-embedding-3-small": 1536,
    "text-embedding-3-large": 3072,
    "text-embedding-ada-002": 1536,
}

_detected_embedding_dim: int | None = None


def reset_detected_embedding_dim() -> None:
    global _detected_embedding_dim
    _detected_embedding_dim = None


def _detect_embedding_dim(embed_fn: Callable[[list[str]], list[list[float]]]) -> int:
    vectors = embed_fn(["ping"])
    if not vectors or not vectors[0]:
        raise RuntimeError("Embedding provider returned no vectors during dimension detection.")
    return len(vectors[0])


def get_active_embedding_dim(
    embed_fn: Callable[[list[str]], list[list[float]]] = embed_texts
) -> int:
    global _detected_embedding_dim
    configured_dim = settings.embedding_dim
    provider = settings.embed_provider

    if provider == "mock":
        return configured_dim or DEFAULT_MOCK_EMBED_DIM
    if provider != "openai":
        return configured_dim or DEFAULT_OLLAMA_EMBED_DIM

    expected_dim = OPENAI_MODEL_DIMENSIONS.get(settings.openai_embed_model)
    if configured_dim is not None:
        if expected_dim is not None and configured_dim != expected_dim:
            raise RuntimeError(
                f"EMBEDDING_DIM={configured_dim} does not match OPENAI_EMBED_MODEL="
                f"{settings.openai_embed_model} (expected {expected_dim})."
            )
        return configured_dim

    if _detected_embedding_dim is None:
        if settings.dev_mode and not settings.openai_api_key:
            return configured_dim or (expected_dim or DEFAULT_MOCK_EMBED_DIM)
        _detected_embedding_dim = _detect_embedding_dim(embed_fn)
    if expected_dim is not None and _detected_embedding_dim != expected_dim:
        raise RuntimeError(
            f"Detected embedding dimension {_detected_embedding_dim} does not match "
            f"OPENAI_EMBED_MODEL={settings.openai_embed_model} expected {expected_dim}."
        )
    return _detected_embedding_dim


def get_cached_embedding_dim() -> int | None:
    if settings.embedding_dim is not None:
        return settings.embedding_dim
    if settings.embed_provider == "mock":
        return DEFAULT_MOCK_EMBED_DIM
    if settings.embed_provider == "openai":
        return _detected_embedding_dim
    return DEFAULT_OLLAMA_EMBED_DIM
