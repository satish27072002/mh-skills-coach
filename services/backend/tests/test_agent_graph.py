from langchain_core.messages import AIMessage, HumanMessage

from app import agent_graph
from app.agent_graph import GraphRuntimeContext, run_agent


def test_crisis_response_does_not_call_llm(monkeypatch):
    """Crisis messages are intercepted by the safety node before any LLM is invoked."""
    llm_called = {"value": False}

    def fail_if_llm_called(*args, **kwargs):
        llm_called["value"] = True
        raise AssertionError("LLM must not be called for crisis messages")

    monkeypatch.setattr(agent_graph, "_graph_model_response", fail_if_llm_called)

    response = run_agent("I want to end my life", context=GraphRuntimeContext())

    assert "coach_message" in response
    assert llm_called["value"] is False


def test_non_crisis_routes_through_coach_llm(monkeypatch):
    """Non-crisis messages flow through supervisor → sentiment → coach, calling the LLM."""
    llm_called = {"value": False}

    def fake_structured_decision(_prompt, _message, model_cls):
        if model_cls is agent_graph.RouteDecision:
            return model_cls(route="COACH")
        if model_cls is agent_graph.SentimentAnalysis:
            return model_cls(
                primary_sentiment="anxious",
                emotional_intensity="medium",
                support_style="calm_and_reassuring",
                user_needs=["reassurance"],
                coach_handoff="Be calm and supportive.",
            )
        return model_cls(action="continue", risk_level="normal", coach_message="", resources=[])

    def fake_graph_model_response(_prompt, _state, *, tools):
        llm_called["value"] = True
        return AIMessage(content="Here is some grounding advice.")

    monkeypatch.setattr(agent_graph, "_structured_decision", fake_structured_decision)
    monkeypatch.setattr(agent_graph, "_graph_model_response", fake_graph_model_response)
    monkeypatch.setattr(agent_graph, "_structured_chat_response", lambda *_: {"coach_message": "hello", "risk_level": "normal"})

    response = run_agent("I feel anxious", context=GraphRuntimeContext())

    assert response["coach_message"] == "hello"
    assert llm_called["value"] is True


def test_coach_route_now_hands_off_to_sentiment_agent_first():
    assert agent_graph._route_after_supervisor({"route": "COACH"}) == "sentiment_agent"


def test_sentiment_agent_writes_structured_handoff_state(monkeypatch):
    analysis = agent_graph.SentimentAnalysis(
        primary_sentiment="overwhelmed",
        emotional_intensity="high",
        support_style="steady_and_structured",
        user_needs=["validation", "practical_steps"],
        coach_handoff="Start by validating their overload, then use a calm step-by-step tone.",
    )

    monkeypatch.setattr(agent_graph, "_structured_decision", lambda *_args, **_kwargs: analysis)

    subgraph = agent_graph.build_sentiment_subgraph()
    update = subgraph.invoke({"messages": [HumanMessage(content="I feel overwhelmed and can't think clearly")]})

    assert update["active_node"] == "sentiment_agent"
    assert update["sentiment_analysis"]["primary_sentiment"] == "overwhelmed"
    assert update["sentiment_analysis"]["support_style"] == "steady_and_structured"
    assert update["sentiment_analysis"]["user_needs"] == ["validation", "practical_steps"]


def test_coach_agent_prompt_includes_sentiment_handoff(monkeypatch):
    captured: dict[str, str] = {}

    def fake_graph_model_response(prompt, state, *, tools):
        captured["prompt"] = prompt
        return AIMessage(content="I can help with that.")

    monkeypatch.setattr(agent_graph, "_graph_model_response", fake_graph_model_response)

    subgraph = agent_graph.build_coach_subgraph([])
    subgraph.invoke(
        {
            "messages": [HumanMessage(content="I feel really anxious today")],
            "sentiment_analysis": {
                "primary_sentiment": "anxious",
                "emotional_intensity": "high",
                "support_style": "calm_and_reassuring",
                "user_needs": ["reassurance", "grounding"],
                "coach_handoff": "Use a calming tone, reassure the user, and avoid overwhelming them with too many steps.",
            },
        }
    )

    assert "Sentiment agent handoff" in captured["prompt"]
    assert "primary_sentiment=anxious" in captured["prompt"]
    assert "support_style=calm_and_reassuring" in captured["prompt"]
    assert "guidance=Use a calming tone, reassure the user, and avoid overwhelming them with too many steps." in captured["prompt"]
