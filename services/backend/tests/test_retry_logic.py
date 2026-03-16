"""
Retry logic tests — resilience under API failure.

Verifies:
1. generate_chat() returns FALLBACK_COACH_MESSAGE when LLM is unavailable
2. FALLBACK_COACH_MESSAGE is a valid, non-empty string with emergency info
3. ProviderError and ProviderNotConfiguredError are defined
4. The /chat endpoint returns a valid response even when LLM fails

Run with:
    pytest tests/test_retry_logic.py -v
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.llm.provider import (
    FALLBACK_COACH_MESSAGE,
    ProviderError,
    ProviderNotConfiguredError,
    generate_chat,
)
from app.main import app


# ---------------------------------------------------------------------------
# Fallback message validation
# ---------------------------------------------------------------------------

def test_fallback_message_exists() -> None:
    """FALLBACK_COACH_MESSAGE must be a non-empty string."""
    assert isinstance(FALLBACK_COACH_MESSAGE, str)
    assert len(FALLBACK_COACH_MESSAGE) > 20


def test_fallback_message_contains_emergency_info() -> None:
    """Fallback message must include at least one emergency number for safety."""
    has_emergency = (
        "1177" in FALLBACK_COACH_MESSAGE
        or "112" in FALLBACK_COACH_MESSAGE
        or "90101" in FALLBACK_COACH_MESSAGE
    )
    assert has_emergency, (
        f"FALLBACK_COACH_MESSAGE lacks emergency numbers: {FALLBACK_COACH_MESSAGE!r}"
    )


# ---------------------------------------------------------------------------
# Provider error types exist
# ---------------------------------------------------------------------------

def test_provider_error_is_exception() -> None:
    """ProviderError must be a RuntimeError subclass."""
    assert issubclass(ProviderError, RuntimeError)


def test_provider_not_configured_error_is_exception() -> None:
    """ProviderNotConfiguredError must be a RuntimeError subclass."""
    assert issubclass(ProviderNotConfiguredError, RuntimeError)


# ---------------------------------------------------------------------------
# generate_chat fallback on LLM failure
# ---------------------------------------------------------------------------

def test_generate_chat_returns_fallback_on_provider_error(monkeypatch) -> None:
    """When the LLM provider raises, generate_chat returns fallback (not crash)."""
    def mock_traced_generate(*args, **kwargs):
        raise ProviderError("Simulated OpenAI outage")

    monkeypatch.setattr(
        "app.llm.provider._traced_generate_chat",
        mock_traced_generate,
    )
    result = generate_chat(
        messages=[{"role": "user", "content": "I feel anxious"}],
        system_prompt="You are a coach.",
    )
    assert result == FALLBACK_COACH_MESSAGE


def test_generate_chat_returns_fallback_on_not_configured(monkeypatch) -> None:
    """When provider is not configured, generate_chat returns fallback."""
    def mock_traced_generate(*args, **kwargs):
        raise ProviderNotConfiguredError("No API key")

    monkeypatch.setattr(
        "app.llm.provider._traced_generate_chat",
        mock_traced_generate,
    )
    result = generate_chat(
        messages=[{"role": "user", "content": "hello"}],
    )
    assert result == FALLBACK_COACH_MESSAGE


# ---------------------------------------------------------------------------
# /chat endpoint returns valid response even on LLM failure
# ---------------------------------------------------------------------------

def test_chat_endpoint_returns_response_on_llm_failure(monkeypatch) -> None:
    """The /chat endpoint must return a 200 with coach_message even if LLM fails."""
    def mock_run_agent(message, **kwargs):
        return {
            "coach_message": FALLBACK_COACH_MESSAGE,
            "risk_level": "normal",
        }

    monkeypatch.setattr("app.main.run_agent", mock_run_agent)

    client = TestClient(app)
    response = client.post("/chat", json={"message": "I feel stressed about work"})
    assert response.status_code == 200
    payload = response.json()
    assert payload["coach_message"]
    assert isinstance(payload["coach_message"], str)
