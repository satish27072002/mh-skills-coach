from __future__ import annotations

from ..config import settings
from .provider import ProviderNotConfiguredError


def get_langchain_chat_model(*, temperature: float | None = None):
    chosen_temperature = settings.llm_temperature if temperature is None else temperature
    if settings.llm_provider == "openai":
        try:
            from langchain_openai import ChatOpenAI
        except ImportError as exc:
            raise ProviderNotConfiguredError(
                "langchain-openai is not installed. Install backend dependencies to run the LangGraph runtime."
            ) from exc
        if not settings.openai_api_key:
            raise ProviderNotConfiguredError(
                "LLM not configured. Set OPENAI_API_KEY or use LLM_PROVIDER=mock."
            )
        return ChatOpenAI(
            model=settings.openai_chat_model,
            api_key=settings.openai_api_key,
            timeout=settings.llm_timeout_seconds,
            temperature=chosen_temperature,
        )
    if settings.llm_provider == "ollama":
        try:
            from langchain_ollama import ChatOllama
        except ImportError as exc:
            raise ProviderNotConfiguredError(
                "langchain-ollama is not installed. Install backend dependencies to run the LangGraph runtime."
            ) from exc
        return ChatOllama(
            model=settings.ollama_model,
            base_url=settings.ollama_base_url,
            temperature=chosen_temperature,
        )
    raise ProviderNotConfiguredError(
        "LangGraph runtime requires an actual chat model provider. LLM_PROVIDER=mock is not supported here."
    )
