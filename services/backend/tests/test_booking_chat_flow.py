import json
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app import db
from app.config import settings
from app.main import app
from app.models import PendingAction, User


ORIGINAL_DATABASE_URL = str(db.engine.url)


@pytest.fixture()
def booking_db():
    db.reset_engine("sqlite+pysqlite:///./test_booking_chat.db")
    db.init_db()
    with db.SessionLocal() as session:
        session.query(PendingAction).delete()
        session.query(User).delete()
        session.commit()
    yield
    db.reset_engine(ORIGINAL_DATABASE_URL)


def _create_user() -> User:
    with db.SessionLocal() as session:
        user = User(email="booker@example.com", name="Booker", is_premium=False)
        session.add(user)
        session.commit()
        session.refresh(user)
        return user


def _pending_count(user_id: str) -> int:
    with db.SessionLocal() as session:
        return session.query(PendingAction).filter(PendingAction.user_id == user_id).count()


def test_booking_missing_email_asks_for_email(booking_db):
    user = _create_user()
    client = TestClient(app)
    client.cookies.set(settings.session_cookie_name, str(user.id))

    response = client.post("/chat", json={"message": "Email therapist for an appointment tomorrow 3pm"})

    assert response.status_code == 200
    payload = response.json()
    assert "email" in payload["coach_message"].lower()
    assert payload.get("requires_confirmation") is False


def test_booking_missing_time_asks_for_time(booking_db):
    user = _create_user()
    client = TestClient(app)
    client.cookies.set(settings.session_cookie_name, str(user.id))

    response = client.post(
        "/chat",
        json={"message": "Email therapist at therapist@example.com for an appointment"}
    )

    assert response.status_code == 200
    payload = response.json()
    assert "date/time" in payload["coach_message"].lower() or "time" in payload["coach_message"].lower()
    assert payload.get("requires_confirmation") is False


def test_booking_complete_creates_pending_and_does_not_send(monkeypatch, booking_db):
    user = _create_user()
    called = {"send": 0}

    def send_stub(*args, **kwargs):
        called["send"] += 1
        return {"ok": True, "message_id": "<msg>"}

    monkeypatch.setattr("app.main.send_email_for_user", send_stub)
    client = TestClient(app)
    client.cookies.set(settings.session_cookie_name, str(user.id))

    response = client.post(
        "/chat",
        json={"message": "Email therapist at therapist@example.com for an appointment on 2026-02-14 15:00"}
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["requires_confirmation"] is True
    assert payload["booking_proposal"]["therapist_email"] == "therapist@example.com"
    assert called["send"] == 0
    assert _pending_count(str(user.id)) == 1


def test_booking_yes_sends_and_clears_pending(monkeypatch, booking_db):
    user = _create_user()
    called = {"send": 0}

    def send_stub(*args, **kwargs):
        called["send"] += 1
        return {"ok": True, "message_id": "<msg>"}

    monkeypatch.setattr("app.main.send_email_for_user", send_stub)
    client = TestClient(app)
    client.cookies.set(settings.session_cookie_name, str(user.id))
    client.post(
        "/chat",
        json={"message": "Email therapist at therapist@example.com for an appointment on 2026-02-14 15:00"}
    )

    response = client.post("/chat", json={"message": "YES"})

    assert response.status_code == 200
    payload = response.json()
    assert "sent" in payload["coach_message"].lower()
    assert called["send"] == 1
    assert _pending_count(str(user.id)) == 0


def test_booking_no_cancels_and_clears_pending(monkeypatch, booking_db):
    user = _create_user()
    called = {"send": 0}

    monkeypatch.setattr(
        "app.main.send_email_for_user",
        lambda *args, **kwargs: called.__setitem__("send", called["send"] + 1)
    )
    client = TestClient(app)
    client.cookies.set(settings.session_cookie_name, str(user.id))
    client.post(
        "/chat",
        json={"message": "Email therapist at therapist@example.com for an appointment on 2026-02-14 15:00"}
    )

    response = client.post("/chat", json={"message": "NO"})

    assert response.status_code == 200
    payload = response.json()
    assert "cancel" in payload["coach_message"].lower()
    assert called["send"] == 0
    assert _pending_count(str(user.id)) == 0


def test_expired_pending_prevents_send(monkeypatch, booking_db):
    user = _create_user()
    called = {"send": 0}

    def send_stub(*args, **kwargs):
        called["send"] += 1
        return {"ok": True}

    monkeypatch.setattr("app.main.send_email_for_user", send_stub)
    expires_past = datetime.now(timezone.utc) - timedelta(minutes=1)
    with db.SessionLocal() as session:
        session.add(
            PendingAction(
                user_id=str(user.id),
                action_type="booking_email",
                payload_json=json.dumps(
                    {
                        "therapist_email": "therapist@example.com",
                        "requested_datetime_iso": "2026-02-14T15:00:00+01:00",
                        "subject": "subject",
                        "body": "body",
                        "reply_to": "booker@example.com"
                    }
                ),
                expires_at=expires_past
            )
        )
        session.commit()

    client = TestClient(app)
    client.cookies.set(settings.session_cookie_name, str(user.id))
    response = client.post("/chat", json={"message": "YES"})

    assert response.status_code == 200
    payload = response.json()
    assert "expired" in payload["coach_message"].lower()
    assert called["send"] == 0
    assert _pending_count(str(user.id)) == 0


def test_crisis_prevents_pending_creation_and_send(monkeypatch, booking_db):
    user = _create_user()
    called = {"send": 0}

    def send_stub(*args, **kwargs):
        called["send"] += 1
        return {"ok": True}

    monkeypatch.setattr("app.main.send_email_for_user", send_stub)
    client = TestClient(app)
    client.cookies.set(settings.session_cookie_name, str(user.id))

    response = client.post(
        "/chat",
        json={"message": "I want to end my life and email therapist@example.com for tomorrow 3pm"}
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload.get("risk_level") == "crisis"
    assert called["send"] == 0
    assert _pending_count(str(user.id)) == 0


def test_yes_without_pending_returns_guidance(booking_db):
    user = _create_user()
    client = TestClient(app)
    client.cookies.set(settings.session_cookie_name, str(user.id))

    response = client.post("/chat", json={"message": "YES"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["coach_message"] == (
        "No pending booking request to confirm. Please provide therapist email + time."
    )
    assert payload.get("requires_confirmation") is False


def test_multiple_sequential_booking_emails_require_separate_confirmations(monkeypatch, booking_db):
    user = _create_user()
    sent_to: list[str] = []

    def send_stub(user_id: str, payload):
        sent_to.append(payload.to)
        return {"ok": True, "message_id": "<msg>"}

    monkeypatch.setattr("app.main.send_email_for_user", send_stub)
    client = TestClient(app)
    client.cookies.set(settings.session_cookie_name, str(user.id))

    first = client.post(
        "/chat",
        json={"message": "Email therapist at first@example.com for an appointment on 2026-02-14 15:00"}
    )
    assert first.status_code == 200
    first_payload = first.json()
    assert first_payload["requires_confirmation"] is True
    assert first_payload["booking_proposal"]["therapist_email"] == "first@example.com"

    confirm_first = client.post("/chat", json={"message": "YES"})
    assert confirm_first.status_code == 200
    assert "sent" in confirm_first.json()["coach_message"].lower()
    assert _pending_count(str(user.id)) == 0

    second = client.post(
        "/chat",
        json={"message": "Email therapist at second@example.com for an appointment on 2026-02-15 16:30"}
    )
    assert second.status_code == 200
    second_payload = second.json()
    assert second_payload["requires_confirmation"] is True
    assert second_payload["booking_proposal"]["therapist_email"] == "second@example.com"
    assert _pending_count(str(user.id)) == 1

    confirm_second = client.post("/chat", json={"message": "YES"})
    assert confirm_second.status_code == 200
    assert "sent" in confirm_second.json()["coach_message"].lower()
    assert _pending_count(str(user.id)) == 0
    assert sent_to == ["first@example.com", "second@example.com"]
