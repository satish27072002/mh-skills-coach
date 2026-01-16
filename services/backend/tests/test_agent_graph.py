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
