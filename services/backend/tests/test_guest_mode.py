"""Tests for guest mode: session creation, prompt counting, and limit enforcement."""

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.main import app, _guest_prompt_counts, GUEST_SESSION_COOKIE_NAME


def _mock_run_agent(message: str, **kwargs):
    return {
        "coach_message": "I hear you. Let's try a grounding exercise.",
        "risk_level": "normal",
        "exercise": {
            "type": "5-4-3-2-1 Grounding",
            "duration_seconds": 300,
            "steps": [
                "Notice 5 things you can see",
                "Notice 4 things you can touch",
                "Notice 3 things you can hear",
                "Notice 2 things you can smell",
                "Notice 1 thing you can taste",
            ],
        },
    }


def test_guest_start_creates_session():
    """POST /guest should create a guest session and return cookie."""
    client = TestClient(app)
    response = client.post("/guest")
    assert response.status_code == 200
    payload = response.json()
    assert payload["is_guest"] is True
    assert payload["guest_prompts_used"] == 0
    assert payload["guest_prompts_limit"] == settings.guest_prompt_limit
    assert payload["guest_prompts_remaining"] == settings.guest_prompt_limit
    # Should set the guest session cookie
    assert GUEST_SESSION_COOKIE_NAME in response.cookies


def test_guest_start_reuses_existing_session():
    """Calling /guest again should reuse the same session."""
    client = TestClient(app)
    r1 = client.post("/guest")
    assert r1.status_code == 200
    # Call again — client automatically sends cookie back
    r2 = client.post("/guest")
    assert r2.status_code == 200
    assert r2.json()["guest_prompts_used"] == 0


def test_me_returns_guest_info():
    """GET /me with a guest session should return guest info, not 401."""
    client = TestClient(app)
    client.post("/guest")
    response = client.get("/me")
    assert response.status_code == 200
    payload = response.json()
    assert payload["is_guest"] is True
    assert payload["is_premium"] is False
    assert payload["guest_prompts_remaining"] == settings.guest_prompt_limit


def test_me_returns_401_without_any_session():
    """GET /me without any session cookie should return 401."""
    client = TestClient(app, cookies={})
    response = client.get("/me")
    assert response.status_code == 401


def test_guest_chat_counts_prompts(monkeypatch):
    """Guest chat messages should decrement the remaining prompt count."""
    monkeypatch.setattr("app.main.run_agent", _mock_run_agent)
    client = TestClient(app)
    client.post("/guest")

    r = client.post("/chat", json={"message": "I feel anxious"})
    assert r.status_code == 200
    payload = r.json()
    assert payload.get("guest_prompts_remaining") == settings.guest_prompt_limit - 1


def test_guest_chat_enforces_limit(monkeypatch):
    """After guest_prompt_limit prompts, further messages should be rejected."""
    monkeypatch.setattr("app.main.run_agent", _mock_run_agent)
    original_limit = settings.guest_prompt_limit
    settings.guest_prompt_limit = 3
    try:
        client = TestClient(app)
        client.post("/guest")

        for i in range(3):
            r = client.post("/chat", json={"message": f"Message {i + 1}"})
            assert r.status_code == 200, f"Message {i + 1} should succeed"

        # 4th message should be blocked
        r = client.post("/chat", json={"message": "One more message"})
        assert r.status_code == 200
        payload = r.json()
        assert "guest_limit_reached" in (payload.get("risk_level") or "")
        assert "Sign in" in payload["coach_message"]
    finally:
        settings.guest_prompt_limit = original_limit


def test_authenticated_user_not_affected_by_guest_limit(monkeypatch):
    """Authenticated users should not be limited by guest prompt count."""
    monkeypatch.setattr("app.main.run_agent", _mock_run_agent)

    from app import db
    from app.models import User

    db.init_db()
    with db.SessionLocal() as session:
        user = User(email="guest_test@example.com", name="Guest Test User")
        session.add(user)
        session.commit()
        session.refresh(user)
        user_id = str(user.id)

    client = TestClient(app)
    client.cookies.set(settings.session_cookie_name, user_id)

    r = client.post("/chat", json={"message": "I feel stressed"})
    assert r.status_code == 200
    payload = r.json()
    assert payload.get("guest_prompts_remaining") is None
    assert payload.get("risk_level") != "guest_limit_reached"


def test_me_returns_is_guest_false_for_authenticated_user():
    """GET /me for an authenticated user should include is_guest=False."""
    from app import db
    from app.models import User

    db.init_db()
    with db.SessionLocal() as session:
        user = User(email="guest_test2@example.com", name="Guest Test User 2")
        session.add(user)
        session.commit()
        session.refresh(user)
        user_id = str(user.id)

    client = TestClient(app)
    client.cookies.set(settings.session_cookie_name, user_id)

    response = client.get("/me")
    assert response.status_code == 200
    payload = response.json()
    assert payload["is_guest"] is False
