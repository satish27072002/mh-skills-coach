from __future__ import annotations

from typing import List

from .llm.provider import ProviderError, ProviderNotConfiguredError, embed_texts


def get_embedding(text: str) -> List[float]:
    try:
        vectors = embed_texts([text])
    except ProviderNotConfiguredError:
        raise
    except ProviderError as exc:
        raise RuntimeError(str(exc)) from exc
    if not vectors:
        raise RuntimeError("Embedding provider returned no vectors.")
    return vectors[0]
