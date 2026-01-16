from __future__ import annotations

import time
from typing import List

import httpx

from .config import settings


def get_embedding(text: str) -> List[float]:
    payload = {"model": settings.ollama_embed_model, "prompt": text}
    url = f"{settings.ollama_base_url}/api/embeddings"
    delays = [0.5, 1.0, 2.0]
    last_exc: Exception | None = None
    for attempt, delay in enumerate(delays, start=1):
        try:
            response = httpx.post(
                url,
                json=payload,
                timeout=60.0
            )
            response.raise_for_status()
            data = response.json()
            embedding = data.get("embedding")
            if not isinstance(embedding, list):
                raise RuntimeError(f"Ollama embeddings response missing embedding vector (model={settings.ollama_embed_model}).")
            return embedding
        except (httpx.ReadTimeout, httpx.ConnectError) as exc:
            last_exc = exc
            if attempt == len(delays):
                break
            time.sleep(delay)
        except httpx.HTTPError as exc:
            raise RuntimeError(
                f"Ollama embeddings endpoint error (base={settings.ollama_base_url}, model={settings.ollama_embed_model})."
            ) from exc

    raise RuntimeError(
        f"Ollama embeddings endpoint is not reachable (base={settings.ollama_base_url}, model={settings.ollama_embed_model})."
    ) from last_exc
