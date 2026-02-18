from __future__ import annotations

import hashlib
import logging
from typing import Any, Protocol

import httpx
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
    before_sleep_log,
)

from ..config import settings

logger = logging.getLogger(__name__)

OPENAI_BASE_URL = "https://api.openai.com/v1"

# ---------------------------------------------------------------------------
# LangSmith @traceable — imported lazily so the app still works when
# langsmith is not installed or LANGSMITH_API_KEY is not set.
# ---------------------------------------------------------------------------
try:
    from langsmith import traceable as _langsmith_traceable  # type: ignore[import]
    _LANGSMITH_AVAILABLE = True
except ImportError:
    _LANGSMITH_AVAILABLE = False

    def _langsmith_traceable(**_kwargs: Any):  # type: ignore[misc]
        """No-op decorator when langsmith is not installed."""
        def decorator(fn: Any) -> Any:
            return fn
        return decorator


def traceable(name: str):
    """Wrap a function with LangSmith tracing if available and configured."""
    if _LANGSMITH_AVAILABLE and settings.langsmith_api_key:
        return _langsmith_traceable(name=name, run_type="llm")
    return _langsmith_traceable(**{}) if _LANGSMITH_AVAILABLE else (lambda fn: fn)


# ---------------------------------------------------------------------------
# Fallback message returned to the user when the LLM is unavailable.
# ---------------------------------------------------------------------------
FALLBACK_COACH_MESSAGE = (
    "I'm sorry, I'm having trouble connecting right now. "
    "Please try again in a moment. If you need immediate support, "
    "you can call 1177 (healthcare advice) or 112 (emergency) in Sweden."
)


class ProviderError(RuntimeError):
    pass


class ConfigurationError(RuntimeError):
    pass


class ProviderNotConfiguredError(RuntimeError):
    pass


class LlmEmbeddingProvider(Protocol):
    def generate_chat(
        self,
        messages: list[dict[str, str]],
        system_prompt: str | None = None,
        **kwargs: Any
    ) -> str:
        ...

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        ...


class OllamaProvider:
    def __init__(
        self,
        base_url: str,
        chat_model: str,
        embed_model: str
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.chat_model = chat_model
        self.embed_model = embed_model

    def generate_chat(
        self,
        messages: list[dict[str, str]],
        system_prompt: str | None = None,
        **kwargs: Any
    ) -> str:
        timeout = kwargs.pop("timeout", 180.0)
        payload_messages = list(messages)
        if system_prompt:
            payload_messages.insert(0, {"role": "system", "content": system_prompt})
        payload = {
            "model": self.chat_model,
            "stream": False,
            "keep_alive": kwargs.pop("keep_alive", "10m"),
            "messages": payload_messages
        }
        try:
            response = httpx.post(
                f"{self.base_url}/api/chat",
                json=payload,
                timeout=timeout
            )
            response.raise_for_status()
        except httpx.TimeoutException as exc:
            raise ProviderError("Ollama chat request timed out.") from exc
        except httpx.HTTPError as exc:
            raise ProviderError("Ollama chat request failed.") from exc

        data = response.json()
        content = data.get("message", {}).get("content") or data.get("response")
        if not content:
            raise ProviderError("Ollama chat response missing content.")
        return str(content)

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        vectors: list[list[float]] = []
        for text in texts:
            last_timeout: Exception | None = None
            for attempt in range(3):
                try:
                    response = httpx.post(
                        f"{self.base_url}/api/embeddings",
                        json={"model": self.embed_model, "prompt": text},
                        timeout=60.0
                    )
                    response.raise_for_status()
                    data = response.json()
                    embedding = data.get("embedding")
                    if not isinstance(embedding, list):
                        raise ProviderError("Ollama embeddings response missing vector.")
                    vectors.append([float(value) for value in embedding])
                    break
                except (httpx.ReadTimeout, httpx.ConnectError) as exc:
                    last_timeout = exc
                    if attempt == 2:
                        raise ProviderError("Ollama embeddings request timed out.") from exc
                except httpx.TimeoutException as exc:
                    last_timeout = exc
                    if attempt == 2:
                        raise ProviderError("Ollama embeddings request timed out.") from exc
                except httpx.HTTPError as exc:
                    raise ProviderError("Ollama embeddings request failed.") from exc
            else:
                raise ProviderError("Ollama embeddings request timed out.") from last_timeout
        return vectors


class OpenAIProvider:
    def __init__(
        self,
        api_key: str | None,
        chat_model: str,
        embed_model: str,
        base_url: str = OPENAI_BASE_URL
    ) -> None:
        if not api_key:
            raise ConfigurationError(
                "OPENAI_API_KEY is required when LLM_PROVIDER or EMBED_PROVIDER is openai."
            )
        self.api_key = api_key
        self.chat_model = chat_model
        self.embed_model = embed_model
        self.base_url = base_url.rstrip("/")

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }

    def generate_chat(
        self,
        messages: list[dict[str, str]],
        system_prompt: str | None = None,
        **kwargs: Any
    ) -> str:
        # Use the configured timeout (default 30s) — never hang forever.
        timeout = kwargs.pop("timeout", settings.llm_timeout_seconds)
        payload_messages = list(messages)
        if system_prompt:
            payload_messages.insert(0, {"role": "system", "content": system_prompt})
        payload: dict[str, Any] = {
            "model": self.chat_model,
            "messages": payload_messages
        }
        if "temperature" in kwargs:
            payload["temperature"] = kwargs["temperature"]
        try:
            response = httpx.post(
                f"{self.base_url}/chat/completions",
                json=payload,
                headers=self._headers(),
                timeout=timeout
            )
            response.raise_for_status()
        except httpx.TimeoutException as exc:
            raise ProviderError("OpenAI chat request timed out.") from exc
        except httpx.HTTPError as exc:
            raise ProviderError("OpenAI chat request failed.") from exc

        data = response.json()
        choices = data.get("choices")
        if not isinstance(choices, list) or not choices:
            raise ProviderError("OpenAI chat response missing choices.")
        message = choices[0].get("message", {})
        content = message.get("content")
        if not isinstance(content, str) or not content.strip():
            raise ProviderError("OpenAI chat response missing content.")
        return content

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        payload = {
            "model": self.embed_model,
            "input": texts
        }
        try:
            response = httpx.post(
                f"{self.base_url}/embeddings",
                json=payload,
                headers=self._headers(),
                timeout=settings.llm_timeout_seconds
            )
            response.raise_for_status()
        except httpx.TimeoutException as exc:
            raise ProviderError("OpenAI embeddings request timed out.") from exc
        except httpx.HTTPError as exc:
            raise ProviderError("OpenAI embeddings request failed.") from exc

        data = response.json().get("data")
        if not isinstance(data, list):
            raise ProviderError("OpenAI embeddings response missing data.")
        ordered = sorted(data, key=lambda item: int(item.get("index", 0)))
        vectors: list[list[float]] = []
        for item in ordered:
            embedding = item.get("embedding")
            if not isinstance(embedding, list):
                raise ProviderError("OpenAI embeddings response contains invalid vector.")
            vectors.append([float(value) for value in embedding])
        return vectors


class MockProvider:
    def __init__(self, embedding_dim: int) -> None:
        self.embedding_dim = embedding_dim

    def generate_chat(
        self,
        messages: list[dict[str, str]],
        system_prompt: str | None = None,
        **kwargs: Any
    ) -> str:
        user_message = str(kwargs.get("user_message") or "")
        if not user_message:
            for message in reversed(messages):
                if message.get("role") == "user":
                    user_message = str(message.get("content") or "")
                    break
        retrieved_count = kwargs.get("retrieved_chunks_count")
        context_note = ""
        if isinstance(retrieved_count, int) and retrieved_count > 0:
            context_note = f" Retrieved context used: {retrieved_count} chunks."
        safe_echo = user_message.strip() or "your last message"
        return f"Mock reply: I read \"{safe_echo}\".{context_note}"

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        return [self._stable_vector(text, self.embedding_dim) for text in texts]

    @staticmethod
    def _stable_vector(text: str, dim: int) -> list[float]:
        vector: list[float] = []
        for idx in range(dim):
            digest = hashlib.sha256(f"{text}:{idx}".encode("utf-8")).digest()
            value = int.from_bytes(digest[:4], "big", signed=False)
            scaled = (value % 2000) / 1000.0 - 1.0
            vector.append(float(f"{scaled:.6f}"))
        return vector


def validate_provider_configuration() -> None:
    if settings.dev_mode:
        return
    if settings.llm_provider == "openai" and not settings.openai_api_key:
        raise ConfigurationError("LLM_PROVIDER=openai requires OPENAI_API_KEY.")
    if settings.embed_provider == "openai" and not settings.openai_api_key:
        raise ConfigurationError("EMBED_PROVIDER=openai requires OPENAI_API_KEY.")


def get_llm_provider() -> LlmEmbeddingProvider:
    if settings.llm_provider == "mock":
        return MockProvider(settings.embedding_dim or 1536)
    if settings.llm_provider == "openai":
        if not settings.openai_api_key and settings.dev_mode:
            raise ProviderNotConfiguredError(
                "LLM not configured. Set OPENAI_API_KEY or use LLM_PROVIDER=mock."
            )
        return OpenAIProvider(
            api_key=settings.openai_api_key,
            chat_model=settings.openai_chat_model,
            embed_model=settings.openai_embed_model
        )
    return OllamaProvider(
        base_url=settings.ollama_base_url,
        chat_model=settings.ollama_model,
        embed_model=settings.ollama_embed_model
    )


def get_embed_provider() -> LlmEmbeddingProvider:
    if settings.embed_provider == "mock":
        return MockProvider(settings.embedding_dim or 1536)
    if settings.embed_provider == "openai":
        if not settings.openai_api_key and settings.dev_mode:
            raise ProviderNotConfiguredError(
                "Embedding not configured. Set OPENAI_API_KEY or use EMBED_PROVIDER=mock."
            )
        return OpenAIProvider(
            api_key=settings.openai_api_key,
            chat_model=settings.openai_chat_model,
            embed_model=settings.openai_embed_model
        )
    return OllamaProvider(
        base_url=settings.ollama_base_url,
        chat_model=settings.ollama_model,
        embed_model=settings.ollama_embed_model
    )


# ---------------------------------------------------------------------------
# Public generate_chat — @traceable + tenacity retries + fallback response
# ---------------------------------------------------------------------------

@retry(
    retry=retry_if_exception_type(ProviderError),
    stop=stop_after_attempt(settings.llm_max_retries),
    wait=wait_exponential(multiplier=1, min=2, max=8),
    before_sleep=before_sleep_log(logger, logging.WARNING),
    reraise=True,
)
def _generate_chat_with_retry(
    messages: list[dict[str, str]],
    system_prompt: str | None = None,
    **kwargs: Any
) -> str:
    """Inner function: calls the LLM provider with tenacity retries.
    Retries up to llm_max_retries times with 2s→4s→8s exponential backoff.
    """
    return get_llm_provider().generate_chat(
        messages=messages,
        system_prompt=system_prompt,
        **kwargs
    )


# Apply LangSmith tracing on top of the retry wrapper
_traced_generate_chat = _langsmith_traceable(
    name="generate_chat", run_type="llm"
)(_generate_chat_with_retry) if _LANGSMITH_AVAILABLE else _generate_chat_with_retry


def generate_chat(
    messages: list[dict[str, str]],
    system_prompt: str | None = None,
    **kwargs: Any
) -> str:
    """Public entrypoint for all LLM chat calls.

    Features:
    - LangSmith @traceable (when LANGSMITH_API_KEY is set)
    - Tenacity retries: up to llm_max_retries (default 3), 2s→4s→8s backoff
    - 30s timeout on OpenAI calls (via settings.llm_timeout_seconds)
    - Graceful fallback: returns FALLBACK_COACH_MESSAGE instead of crashing
      when all retries are exhausted
    """
    try:
        return _traced_generate_chat(
            messages=messages,
            system_prompt=system_prompt,
            **kwargs
        )
    except (ProviderError, ProviderNotConfiguredError) as exc:
        logger.error(
            "LLM call failed after retries, returning fallback response. error=%s",
            exc,
        )
        return FALLBACK_COACH_MESSAGE


def embed_texts(texts: list[str]) -> list[list[float]]:
    return get_embed_provider().embed_texts(texts)


def probe_ollama_connectivity(timeout: float = 0.8) -> bool:
    try:
        response = httpx.get(f"{settings.ollama_base_url}/api/tags", timeout=timeout)
        return response.status_code == 200
    except httpx.HTTPError:
        return False


def probe_openai_connectivity(timeout: float = 8.0) -> bool:
    if not settings.openai_api_key:
        return False
    try:
        response = httpx.get(
            f"{OPENAI_BASE_URL}/models",
            headers={"Authorization": f"Bearer {settings.openai_api_key}"},
            timeout=timeout
        )
        return response.status_code == 200
    except httpx.HTTPError:
        return False
