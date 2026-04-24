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


# ---------------------------------------------------------------------------
# Tier 1.1 — retry + fallback for the LangGraph path
#
# The three graph helpers (_graph_model_response, _structured_chat_response,
# _structured_decision) wrap model.invoke with tenacity retries and a
# conservative fallback.  These tests force model.invoke to raise and assert
# the helper returns a safe default instead of propagating the exception.
# ---------------------------------------------------------------------------

from langchain_core.messages import AIMessage, HumanMessage  # noqa: E402
from app import agent_graph  # noqa: E402
from app.agent_graph import GraphRuntimeContext, run_agent  # noqa: E402


def test_graph_model_response_retries_then_returns_fallback(monkeypatch) -> None:
    """Every attempt raises → helper returns AIMessage(FALLBACK_COACH_MESSAGE)."""
    call_count = {"value": 0}

    class _BrokenModel:
        def bind_tools(self, _tools):
            return self

        def invoke(self, _messages):
            call_count["value"] += 1
            raise RuntimeError("simulated OpenAI outage")

    monkeypatch.setattr(agent_graph, "get_langchain_chat_model", lambda *a, **kw: _BrokenModel())

    result = agent_graph._graph_model_response(
        "system prompt",
        {"messages": [HumanMessage(content="hi")]},
        tools=[],
    )

    assert isinstance(result, AIMessage)
    assert result.content == FALLBACK_COACH_MESSAGE
    # Tenacity retried llm_max_retries attempts total.
    assert call_count["value"] == agent_graph.settings.llm_max_retries


def test_graph_model_response_recovers_after_transient_failure(monkeypatch) -> None:
    """First attempt fails, second succeeds → helper returns the successful response."""
    attempts = {"value": 0}

    class _FlakyModel:
        def bind_tools(self, _tools):
            return self

        def invoke(self, _messages):
            attempts["value"] += 1
            if attempts["value"] < 2:
                raise RuntimeError("transient network hiccup")
            return AIMessage(content="here is real coaching advice")

    monkeypatch.setattr(agent_graph, "get_langchain_chat_model", lambda *a, **kw: _FlakyModel())

    result = agent_graph._graph_model_response(
        "system prompt",
        {"messages": [HumanMessage(content="hi")]},
        tools=[],
    )

    assert isinstance(result, AIMessage)
    assert result.content == "here is real coaching advice"
    assert attempts["value"] == 2


def test_structured_chat_response_returns_fallback_dict_on_exhaustion(monkeypatch) -> None:
    """Every attempt raises → helper returns a safe ChatResponse dict."""

    class _BrokenStructured:
        def with_structured_output(self, _model_cls):
            return self

        def invoke(self, _messages):
            raise RuntimeError("simulated OpenAI 502")

    monkeypatch.setattr(agent_graph, "get_langchain_chat_model", lambda *a, **kw: _BrokenStructured())

    result = agent_graph._structured_chat_response(
        "finalize prompt",
        {"messages": [HumanMessage(content="hi")]},
    )

    assert isinstance(result, dict)
    assert result.get("coach_message") == FALLBACK_COACH_MESSAGE
    assert result.get("risk_level") == "normal"


@pytest.mark.parametrize(
    "model_cls_name,expected_attr,expected_value",
    [
        ("RouteDecision", "route", "COACH"),
        ("SafetyDecision", "action", "stop"),
        ("SentimentAnalysis", "primary_sentiment", "mixed"),
    ],
)
def test_structured_decision_returns_safe_default_on_exhaustion(
    monkeypatch, model_cls_name, expected_attr, expected_value
) -> None:
    """Each structured decision type falls back to a conservative default."""
    model_cls = getattr(agent_graph, model_cls_name)

    class _BrokenStructured:
        def with_structured_output(self, _model_cls):
            return self

        def invoke(self, _messages):
            raise RuntimeError("simulated provider failure")

    monkeypatch.setattr(agent_graph, "get_langchain_chat_model", lambda *a, **kw: _BrokenStructured())

    result = agent_graph._structured_decision("prompt", "user message", model_cls)

    assert isinstance(result, model_cls)
    assert getattr(result, expected_attr) == expected_value


def test_full_graph_survives_total_llm_outage(monkeypatch) -> None:
    """End-to-end: every LLM call fails → run_agent still returns a valid
    ChatResponse dict containing FALLBACK_COACH_MESSAGE.  Never a 500.
    """

    class _AlwaysBroken:
        def with_structured_output(self, _model_cls):
            return self

        def bind_tools(self, _tools):
            return self

        def invoke(self, _messages):
            raise RuntimeError("total outage")

    monkeypatch.setattr(agent_graph, "get_langchain_chat_model", lambda *a, **kw: _AlwaysBroken())

    response = run_agent("I feel anxious and need help", context=GraphRuntimeContext())

    assert isinstance(response, dict)
    assert "coach_message" in response
    # Safety gate default was "stop" with FALLBACK_COACH_MESSAGE; the graph
    # short-circuits to END before reaching the coach subgraph.
    assert response["coach_message"] == FALLBACK_COACH_MESSAGE
    assert response.get("risk_level") == "normal"
