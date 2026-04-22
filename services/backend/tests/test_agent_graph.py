from langchain_core.messages import AIMessage, HumanMessage

from app import agent_graph
from app.agent_graph import run_agent


def test_crisis_response_does_not_call_llm():
    called = {"llm": False, "retrieve": False}

    def retrieve_stub(_state):
        called["retrieve"] = True
        return {"retrieved_chunks": []}

    def llm_stub(_state):
        called["llm"] = True
        return {"response_json": {"coach_message": "should not be used"}}

    response = run_agent(
        "I want to end my life",
        retrieve_fn=retrieve_stub,
        llm_fn=llm_stub
    )

    assert "coach_message" in response
    assert called["llm"] is False
    assert called["retrieve"] is False


def test_non_crisis_calls_retrieve_and_llm():
    called = {"llm": False, "retrieve": False}

    def retrieve_stub(_state):
        called["retrieve"] = True
        return {"retrieved_chunks": [{"text": "chunk"}]}

    def llm_stub(_state):
        called["llm"] = True
        return {"response_json": {"coach_message": "hello"}}

    response = run_agent(
        "I feel anxious",
        retrieve_fn=retrieve_stub,
        llm_fn=llm_stub
    )

    assert response["coach_message"] == "hello"
    assert called["retrieve"] is True
    assert called["llm"] is True


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
