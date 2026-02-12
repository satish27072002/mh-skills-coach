from __future__ import annotations

from typing import Any, Protocol

import httpx

from ..config import settings


OPENAI_BASE_URL = "https://api.openai.com/v1"


class ProviderError(RuntimeError):
    pass


class ConfigurationError(RuntimeError):
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
        timeout = kwargs.pop("timeout", 30.0)
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
                timeout=30.0
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


def validate_provider_configuration() -> None:
    if settings.llm_provider == "openai" and not settings.openai_api_key:
        raise ConfigurationError("LLM_PROVIDER=openai requires OPENAI_API_KEY.")
    if settings.embed_provider == "openai" and not settings.openai_api_key:
        raise ConfigurationError("EMBED_PROVIDER=openai requires OPENAI_API_KEY.")


def get_llm_provider() -> LlmEmbeddingProvider:
    if settings.llm_provider == "openai":
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
    if settings.embed_provider == "openai":
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


def generate_chat(
    messages: list[dict[str, str]],
    system_prompt: str | None = None,
    **kwargs: Any
) -> str:
    return get_llm_provider().generate_chat(messages=messages, system_prompt=system_prompt, **kwargs)


def embed_texts(texts: list[str]) -> list[list[float]]:
    return get_embed_provider().embed_texts(texts)


def probe_ollama_connectivity(timeout: float = 0.8) -> bool:
    try:
        response = httpx.get(f"{settings.ollama_base_url}/api/tags", timeout=timeout)
        return response.status_code == 200
    except httpx.HTTPError:
        return False


def probe_openai_connectivity(timeout: float = 3.0) -> bool:
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
