import pytest
from fastapi.testclient import TestClient

from app import db
from app.config import settings
from app.main import app
from app.models import PendingAction, User
from app.schemas import TherapistResult


ORIGINAL_DATABASE_URL = str(db.engine.url)


def _reset_db():
    db.reset_engine("sqlite+pysqlite:///./test_therapists.db")
    db.init_db()
    with db.SessionLocal() as session:
        session.query(PendingAction).delete()
        session.query(User).delete()
        session.commit()


@pytest.fixture()
def test_db():
    _reset_db()
    yield
    db.reset_engine(ORIGINAL_DATABASE_URL)


def test_therapist_search_requires_sign_in_when_unauthenticated(test_db):
    client = TestClient(app)

    response = client.post("/chat", json={"message": "find therapist near me"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["premium_cta"]["enabled"] is True
    assert "sign in" in payload["coach_message"].lower()
    assert payload.get("resources") is None
    assert payload.get("therapists") is None


def test_therapist_search_requires_premium_for_authenticated_user(test_db):
    with db.SessionLocal() as session:
        user = User(email="free@example.com", name="Free User", is_premium=False)
        session.add(user)
        session.commit()
        session.refresh(user)

    client = TestClient(app)
    client.cookies.set(settings.session_cookie_name, str(user.id))

    response = client.post("/chat", json={"message": "find therapist in Stockholm"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["premium_cta"]["enabled"] is True
    assert "premium" in payload["coach_message"].lower()


def test_therapist_search_returns_results_for_premium(monkeypatch, test_db):
    with db.SessionLocal() as session:
        user = User(email="premium@example.com", name="Premium User", is_premium=True)
        session.add(user)
        session.commit()
        session.refresh(user)

    called = {"count": 0}

    def stub_search(
        location: str,
        radius_km: int | None = None,
        specialty: str | None = None,
        limit: int = 10,
    ):
        called["count"] += 1
        assert location
        return [
            TherapistResult(
                name="Stockholm Therapy",
                address="1 Main St, Stockholm",
                url="https://example.com/therapy",
                phone="+46 8 000 000",
                distance_km=2.4
            )
        ]

    monkeypatch.setattr("app.main._run_therapist_search", stub_search)
    client = TestClient(app)
    client.cookies.set(settings.session_cookie_name, str(user.id))

    response = client.post("/chat", json={"message": "find therapist in Stockholm"})

    assert response.status_code == 200
    payload = response.json()
    assert called["count"] == 1
    assert payload.get("premium_cta") is None
    assert payload["therapists"][0]["name"] == "Stockholm Therapy"


def test_prescription_request_does_not_trigger_paywall(test_db):
    client = TestClient(app)

    response = client.post("/chat", json={"message": "Can you prescribe medication?"})

    assert response.status_code == 200
    payload = response.json()
    assert "prescriptions" in payload["coach_message"].lower()
    assert "clinician" in payload["coach_message"].lower()
    assert payload["risk_level"] == "crisis"
    assert payload["premium_cta"]["enabled"] is True


def test_therapist_search_prompt_does_not_trigger_booking(monkeypatch, test_db):
    with db.SessionLocal() as session:
        user = User(email="premium2@example.com", name="Premium User 2", is_premium=True)
        session.add(user)
        session.commit()
        session.refresh(user)

    calls = {"count": 0}

    def stub_search(location_text, radius_km=None, specialty=None, limit=5):
        calls["count"] += 1
        return [
            TherapistResult(
                name="Anxiety Center",
                address="2 Main St, Stockholm",
                url="https://example.com/anxiety",
                phone="+46 8 111 111",
                distance_km=1.8
            )
        ]

    monkeypatch.setattr("app.main.mcp_therapist_search", stub_search)
    client = TestClient(app)
    client.cookies.set(settings.session_cookie_name, str(user.id))

    response = client.post(
        "/chat",
        json={"message": "Find 3 therapists/clinics near Stockholm within 5 km for anxiety"}
    )

    assert response.status_code == 200
    payload = response.json()
    assert calls["count"] == 1
    assert payload.get("therapists")
    assert payload.get("booking_proposal") is None
    assert payload.get("requires_confirmation") is not True


def test_therapist_search_prompt_with_specialty_uses_fallback(monkeypatch, test_db):
    with db.SessionLocal() as session:
        user = User(email="premium3@example.com", name="Premium User 3", is_premium=True)
        session.add(user)
        session.commit()
        session.refresh(user)

    calls: list[dict[str, object]] = []

    def stub_search(
        location: str,
        radius_km: int | None = None,
        specialty: str | None = None,
        limit: int = 10,
    ):
        calls.append({"location": location, "radius_km": radius_km, "specialty": specialty})
        if specialty:
            return []
        return [
            TherapistResult(
                name="Fallback Clinic",
                address="3 Main St, Stockholm",
                url="https://example.com/fallback",
                phone="+46 8 222 222",
                distance_km=4.3
            )
        ]

    monkeypatch.setattr("app.main._run_therapist_search", stub_search)
    client = TestClient(app)
    client.cookies.set(settings.session_cookie_name, str(user.id))

    response = client.post(
        "/chat",
        json={"message": "Find therapists near Stockholm within 10 km for anxiety"}
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload.get("therapists")
    assert payload["therapists"][0]["name"] == "Fallback Clinic"
    assert payload["booking_proposal"] is None
    assert "no exact specialty match" in payload["coach_message"].lower()
    assert calls[0] == {"location": "Stockholm", "radius_km": 10, "specialty": "anxiety"}
    assert calls[1] == {"location": "Stockholm", "radius_km": 10, "specialty": None}
    assert len(calls) == 2


def test_booking_prompt_triggers_booking_proposal_not_therapist_search(monkeypatch, test_db):
    with db.SessionLocal() as session:
        user = User(email="booking@example.com", name="Booking User", is_premium=True)
        session.add(user)
        session.commit()
        session.refresh(user)

    def fail_search(*args, **kwargs):
        raise AssertionError("therapist search should not run for booking prompt")

    monkeypatch.setattr("app.main._run_therapist_search", fail_search)
    client = TestClient(app)
    client.cookies.set(settings.session_cookie_name, str(user.id))

    response = client.post(
        "/chat",
        json={"message": "Email therapist at therapist@example.com for an appointment on 2026-02-14 15:00"}
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload.get("booking_proposal") is not None
    assert payload.get("requires_confirmation") is True
