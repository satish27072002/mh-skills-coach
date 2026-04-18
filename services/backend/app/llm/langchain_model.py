from __future__ import annotations

from ..config import settings
from .provider import ProviderNotConfiguredError


def get_langchain_chat_model(*, temperature: float | None = None):
    chosen_temperature = settings.llm_temperature if temperature is None else temperature
    if settings.llm_provider != "openai":
        raise ProviderNotConfiguredError(
            "LangGraph runtime requires OpenAI. LLM_PROVIDER=mock is not supported here."
        )
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
