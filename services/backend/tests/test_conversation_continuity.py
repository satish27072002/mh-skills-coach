from __future__ import annotations

from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage

from app import agent_graph
from app.agent_graph import GraphRuntimeContext, load_conversation_history, run_agent
from app.config import settings
from app.main import app


def test_load_conversation_history_returns_empty_for_new_thread() -> None:
    assert load_conversation_history("session:continuity-empty-thread") == []


def test_run_agent_persists_history_by_session_id(monkeypatch) -> None:
    def fake_structured_decision(_prompt, _message, model_cls):
        if model_cls is agent_graph.RouteDecision:
            return model_cls(route="COACH")
        if model_cls is agent_graph.SentimentAnalysis:
            return model_cls(
                primary_sentiment="stressed",
                emotional_intensity="medium",
                support_style="gentle_and_validating",
                user_needs=["validation"],
                coach_handoff="Respond supportively.",
            )
        return model_cls(action="continue", risk_level="normal", coach_message="", resources=[])

    monkeypatch.setattr(agent_graph, "_structured_decision", fake_structured_decision)
    monkeypatch.setattr(agent_graph, "_graph_model_response", lambda *_args, **_kwargs: AIMessage(content="I can help."))
    monkeypatch.setattr(agent_graph, "_structured_chat_response", lambda *_args, **_kwargs: {"coach_message": "I can help.", "risk_level": "normal"})

    session_id = "session:continuity-direct"
    run_agent("First message", session_id=session_id, context=GraphRuntimeContext())
    run_agent("Second message", session_id=session_id, context=GraphRuntimeContext())
    history = load_conversation_history(session_id)

    assert len(history) >= 4
    assert history[0] == {"role": "user", "content": "First message"}
    assert history[1] == {"role": "assistant", "content": "I can help."}
    assert history[-2] == {"role": "user", "content": "Second message"}
    assert history[-1] == {"role": "assistant", "content": "I can help."}


def test_chat_endpoint_accumulates_history_in_langgraph_thread(monkeypatch) -> None:
    def fake_structured_decision(_prompt, _message, model_cls):
        if model_cls is agent_graph.RouteDecision:
            return model_cls(route="COACH")
        if model_cls is agent_graph.SentimentAnalysis:
            return model_cls(
                primary_sentiment="overwhelmed",
                emotional_intensity="medium",
                support_style="calm_and_reassuring",
                user_needs=["grounding"],
                coach_handoff="Use a calm tone.",
            )
        return model_cls(action="continue", risk_level="normal", coach_message="", resources=[])

    monkeypatch.setattr(agent_graph, "_structured_decision", fake_structured_decision)
    monkeypatch.setattr(agent_graph, "_graph_model_response", lambda *_args, **_kwargs: AIMessage(content="Response from graph."))
    monkeypatch.setattr(agent_graph, "_structured_chat_response", lambda *_args, **_kwargs: {"coach_message": "Response from graph.", "risk_level": "normal"})
    monkeypatch.setattr(agent_graph, "_current_booking_session", lambda _context: {"status": "NO_PENDING", "pending": False, "expired": False, "payload": {}, "expires_at": None})

    client = TestClient(app)
    session_cookie = "continuity-test-cookie"
    client.cookies.set(settings.session_cookie_name, session_cookie)
    session_id = f"session:{session_cookie}"

    for message in [
        "I feel stressed about work",
        "It has been overwhelming lately",
        "Do you have any tips?",
    ]:
        response = client.post("/chat", json={"message": message})
        assert response.status_code == 200

    history = load_conversation_history(session_id)
    assert len(history) >= 6
    assert history[0]["role"] == "user"
    assert history[1]["role"] == "assistant"
    assert history[-2]["content"] == "Do you have any tips?"
    assert history[-1]["content"] == "Response from graph."
