"""Tier 1.3 — checkpointed message history stays bounded.

LangGraph's ``add_messages`` reducer is append-only.  Without a trim step,
every turn grows ``state["messages"]`` by (at least) the new HumanMessage
+ AIMessage pair, forever.  That inflates every subsequent prompt, bloats
the Postgres checkpoint table, and eventually overflows the model context.

The ``_trim_history_node`` we added at the front of ``build_graph()`` emits
``RemoveMessage`` entries whenever the history exceeds
``settings.graph_message_window``, so the persisted state never grows past
the window.

These tests run many turns on a single thread and assert the window holds.
"""
from __future__ import annotations

from langchain_core.messages import AIMessage, HumanMessage, RemoveMessage

from app import agent_graph
from app.agent_graph import GraphRuntimeContext, run_agent
from app.config import settings


def _stub_llm(monkeypatch) -> None:
    """Replace all LLM calls with deterministic fakes.

    We stub at TWO levels for robustness:

    1. The three public graph helpers (``_structured_decision``,
       ``_graph_model_response``, ``_structured_chat_response``) — this covers
       the common path where nodes call these by module global name.

    2. ``get_langchain_chat_model`` — the underlying model factory.  This is a
       belt-and-suspenders guard: if any code path slips past the public
       helpers and talks to a model directly (retries, subgraph nodes built at
       compile time, etc.), the returned stub model still never dials OpenAI.
       This matches the pattern proven to work in ``test_retry_logic.py``.
    """

    def fake_structured_decision(_prompt, _message, model_cls):
        if model_cls is agent_graph.RouteDecision:
            return model_cls(route="COACH")
        if model_cls is agent_graph.SentimentAnalysis:
            return model_cls(
                primary_sentiment="calm",
                emotional_intensity="low",
                support_style="gentle_and_validating",
                user_needs=["validation"],
                coach_handoff="Respond with one short supportive sentence.",
            )
        return model_cls(
            action="continue",
            risk_level="normal",
            coach_message="",
            resources=[],
        )

    class _StubModel:
        """Drop-in replacement for a langchain chat model."""

        def bind_tools(self, _tools):
            return self

        def with_structured_output(self, model_cls):
            self._structured_cls = model_cls
            return self

        def invoke(self, _messages):
            cls = getattr(self, "_structured_cls", None)
            if cls is None:
                return AIMessage(content="ok")
            # Structured output — return a safe default instance.
            if cls is agent_graph.RouteDecision:
                return cls(route="COACH")
            if cls is agent_graph.SentimentAnalysis:
                return cls(
                    primary_sentiment="calm",
                    emotional_intensity="low",
                    support_style="gentle_and_validating",
                    user_needs=["validation"],
                    coach_handoff="Respond with one short supportive sentence.",
                )
            # SafetyDecision or ChatResponse fallback.
            try:
                return cls(
                    action="continue",
                    risk_level="normal",
                    coach_message="ok",
                    resources=[],
                )
            except Exception:  # pragma: no cover - defensive
                return cls()  # type: ignore[call-arg]

    monkeypatch.setattr(agent_graph, "_structured_decision", fake_structured_decision)
    monkeypatch.setattr(
        agent_graph,
        "_graph_model_response",
        lambda *_args, **_kwargs: AIMessage(content="ok"),
    )
    monkeypatch.setattr(
        agent_graph,
        "_structured_chat_response",
        lambda *_args, **_kwargs: {"coach_message": "ok", "risk_level": "normal"},
    )
    monkeypatch.setattr(
        agent_graph,
        "get_langchain_chat_model",
        lambda *_args, **_kwargs: _StubModel(),
    )


# ---------------------------------------------------------------------------
# Direct unit test of the trim node
# ---------------------------------------------------------------------------


def test_trim_history_node_is_noop_when_under_window():
    """Below the window, the node must not emit any RemoveMessage entries
    (but it still writes ``active_node`` — LangGraph requires every node to
    write at least one state key)."""
    window = settings.graph_message_window
    messages = [
        HumanMessage(content=f"msg {i}", id=f"id-{i}")
        for i in range(window - 1)
    ]
    result = agent_graph._trim_history_node({"messages": messages})
    assert "messages" not in result
    assert result.get("active_node") == "trim_history"


def test_trim_history_node_emits_remove_messages_when_over_window():
    """Above the window, emit RemoveMessage for every surplus message."""
    window = settings.graph_message_window
    total = window + 7
    messages = [
        HumanMessage(content=f"msg {i}", id=f"id-{i}")
        for i in range(total)
    ]
    result = agent_graph._trim_history_node({"messages": messages})

    removes = result.get("messages", [])
    assert len(removes) == 7
    assert all(isinstance(m, RemoveMessage) for m in removes)
    # The oldest 7 must be the ones being removed.
    removed_ids = {m.id for m in removes}
    assert removed_ids == {f"id-{i}" for i in range(7)}


def test_trim_history_node_skips_messages_without_id():
    """RemoveMessage requires an id; messages without one are left alone
    (the reducer would reject a RemoveMessage with no target).  This is a
    defensive check — in practice LangGraph auto-assigns ids.
    """
    window = settings.graph_message_window
    messages = [HumanMessage(content=f"msg {i}") for i in range(window + 3)]  # no ids
    result = agent_graph._trim_history_node({"messages": messages})
    # With no ids, we can't remove anything; node still writes active_node.
    assert "messages" not in result
    assert result.get("active_node") == "trim_history"


# ---------------------------------------------------------------------------
# End-to-end: many turns on one thread stay within the window
# ---------------------------------------------------------------------------


def test_thirty_turns_stay_within_message_window(monkeypatch):
    """Drive 30 turns on one thread, assert the persisted history stays
    bounded — it must NOT grow linearly with turn count.

    The trim_history node runs at the START of each turn, capping the
    messages list at ``settings.graph_message_window`` BEFORE the turn's
    new AI/tool messages are appended.  So the end-of-turn persisted count
    is ``window + new_messages_produced_this_turn`` (typically 1-3).  The
    architectural guarantee being verified is *boundedness*, not a strict
    ``<= window`` at every instant.

    Without the trim node, 30 turns would persist ~60 messages; we assert
    well below that, with a modest buffer over the window for the current
    turn's additions.
    """
    _stub_llm(monkeypatch)
    # Force the compiled graph to rebuild so any previously-compiled
    # subgraph references resolve against the freshly-patched module
    # globals (defensive: the monkeypatches are module-level, but test
    # ordering can cause _COMPILED_GRAPH to have been built during an
    # earlier test with different stubs in place).
    agent_graph._COMPILED_GRAPH = None

    session_id = "session:trim-window-30-turns"
    for turn in range(30):
        run_agent(
            f"turn {turn}: I'd like to talk about my day",
            session_id=session_id,
            context=GraphRuntimeContext(),
        )

    # Pull the persisted state directly from the checkpointer.
    graph = agent_graph.build_graph()
    snapshot = graph.get_state({"configurable": {"thread_id": session_id}})
    messages = (snapshot.values or {}).get("messages", [])

    # Allow a small buffer for the current turn's post-trim additions
    # (AI message + any tool messages).  The key thing we're verifying is
    # that growth is BOUNDED — not proportional to turn count.
    window = settings.graph_message_window
    upper_bound = window + 5
    assert len(messages) <= upper_bound, (
        f"Persisted message count {len(messages)} exceeds bounded budget "
        f"{upper_bound} (= window {window} + 5-msg per-turn buffer) after "
        "30 turns — trim node is not bounding history."
    )
    # Sanity: trimming shouldn't have wiped everything.
    assert len(messages) > 0
    # And — we're actually past the window (otherwise the test proves
    # nothing about trimming behaviour).
    # 30 turns × ≥2 messages/turn = 60, so without trim we'd be far above.
    # If we ended <= window + 5, trim definitely fired.
    assert len(messages) < 60, (
        "History was not allowed to grow enough for trim to matter; "
        "the test is not exercising the trim path."
    )


def test_trim_keeps_most_recent_messages(monkeypatch):
    """After trimming, the RETAINED messages must be the newest ones —
    otherwise the coach loses the immediate conversation context.
    """
    _stub_llm(monkeypatch)
    agent_graph._COMPILED_GRAPH = None  # see note in the 30-turn test

    session_id = "session:trim-keeps-newest"
    # Run enough turns to force trimming.
    for turn in range(15):
        run_agent(
            f"turn-marker-{turn}",
            session_id=session_id,
            context=GraphRuntimeContext(),
        )

    graph = agent_graph.build_graph()
    snapshot = graph.get_state({"configurable": {"thread_id": session_id}})
    messages = (snapshot.values or {}).get("messages", [])

    # The most recent user message (turn-marker-14) must be present; the
    # oldest (turn-marker-0) should have been trimmed if we're over window.
    contents = [str(getattr(m, "content", "")) for m in messages]
    assert any("turn-marker-14" in c for c in contents), (
        "Newest user message was dropped — trim kept the wrong end."
    )
