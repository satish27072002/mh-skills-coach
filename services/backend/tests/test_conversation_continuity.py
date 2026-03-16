"""
Conversation continuity tests — context retained across 3+ message exchanges.

Verifies:
1. Conversation history accumulates across multiple /chat requests
2. History is keyed by session (different sessions have separate histories)
3. History is capped at max turns
4. Both user and assistant messages are stored

Run with:
    pytest tests/test_conversation_continuity.py -v
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.main import (
    _conversation_store,
    _load_history,
    _append_to_history,
    _save_history,
    app,
)


# ---------------------------------------------------------------------------
# Direct unit tests on history functions
# ---------------------------------------------------------------------------

def test_append_to_history_stores_both_roles() -> None:
    """_append_to_history stores both user and assistant messages."""
    key = "test:append"
    _conversation_store.pop(key, None)

    _append_to_history(key, "Hello", "Hi there!")
    history = _load_history(key)

    assert len(history) == 2
    assert history[0] == {"role": "user", "content": "Hello"}
    assert history[1] == {"role": "assistant", "content": "Hi there!"}

    _conversation_store.pop(key, None)


def test_load_history_returns_empty_for_new_session() -> None:
    """_load_history returns an empty list for an unknown session key."""
    history = _load_history("nonexistent:key:12345")
    assert history == []


def test_history_accumulates_across_exchanges() -> None:
    """Multiple _append_to_history calls accumulate in the store."""
    key = "test:accumulate"
    _conversation_store.pop(key, None)

    _append_to_history(key, "msg1", "reply1")
    _append_to_history(key, "msg2", "reply2")
    _append_to_history(key, "msg3", "reply3")

    history = _load_history(key)
    assert len(history) == 6  # 3 exchanges × 2 messages each
    assert history[4] == {"role": "user", "content": "msg3"}
    assert history[5] == {"role": "assistant", "content": "reply3"}

    _conversation_store.pop(key, None)


def test_history_capped_at_max_turns() -> None:
    """_save_history caps messages at conversation_history_max_turns × 2."""
    key = "test:cap"
    _conversation_store.pop(key, None)

    max_turns = settings.conversation_history_max_turns
    # Insert more messages than the cap
    history = []
    for i in range(max_turns + 5):
        history.append({"role": "user", "content": f"msg{i}"})
        history.append({"role": "assistant", "content": f"reply{i}"})

    _save_history(key, history)
    saved = _load_history(key)

    max_messages = max_turns * 2
    assert len(saved) == max_messages
    # Should keep the most recent messages
    assert saved[-1]["content"] == f"reply{max_turns + 4}"

    _conversation_store.pop(key, None)


def test_separate_sessions_have_separate_histories() -> None:
    """Different session keys maintain independent conversation histories."""
    key_a = "test:session_a"
    key_b = "test:session_b"
    _conversation_store.pop(key_a, None)
    _conversation_store.pop(key_b, None)

    _append_to_history(key_a, "Hello from A", "Hi A!")
    _append_to_history(key_b, "Hello from B", "Hi B!")

    history_a = _load_history(key_a)
    history_b = _load_history(key_b)

    assert len(history_a) == 2
    assert len(history_b) == 2
    assert history_a[0]["content"] == "Hello from A"
    assert history_b[0]["content"] == "Hello from B"

    _conversation_store.pop(key_a, None)
    _conversation_store.pop(key_b, None)


# ---------------------------------------------------------------------------
# Integration test — /chat endpoint accumulates history
# ---------------------------------------------------------------------------

def test_chat_endpoint_accumulates_history(monkeypatch) -> None:
    """Three sequential /chat requests with the same session should accumulate history."""
    call_count = {"n": 0}

    def mock_run_agent(message, **kwargs):
        call_count["n"] += 1
        return {
            "coach_message": f"Response {call_count['n']} to your message.",
            "risk_level": "normal",
        }

    monkeypatch.setattr("app.main.run_agent", mock_run_agent)

    client = TestClient(app)

    # Send 3 messages with the same session (TestClient maintains cookies)
    messages = [
        "I feel stressed about work",
        "It's been really overwhelming lately",
        "Do you have any tips for managing this?",
    ]

    for msg in messages:
        response = client.post("/chat", json={"message": msg})
        assert response.status_code == 200

    # Verify history was accumulated for the session
    # The session key for unauthenticated TestClient is based on IP
    matching_keys = [k for k in _conversation_store if _conversation_store[k]]
    assert len(matching_keys) >= 1, "No conversation history found after 3 messages"

    # Get the history for any active session
    history = _conversation_store[matching_keys[0]]
    # Should have at least 6 entries (3 user + 3 assistant)
    assert len(history) >= 6, (
        f"Expected ≥6 history entries after 3 exchanges, got {len(history)}"
    )
