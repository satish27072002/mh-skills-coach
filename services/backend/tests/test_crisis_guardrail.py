import pytest
from fastapi.testclient import TestClient

from app import db
from app.config import settings
from app.main import app
from app.models import PendingAction, User


ORIGINAL_DATABASE_URL = str(db.engine.url)


def _reset_db() -> None:
    db.reset_engine("sqlite+pysqlite:///./test_crisis_guardrail.db")
    db.init_db()
    with db.SessionLocal() as session:
        session.query(PendingAction).delete()
        session.query(User).delete()
        session.commit()


@pytest.fixture()
def crisis_db():
    _reset_db()
    yield
    db.reset_engine(ORIGINAL_DATABASE_URL)


def test_crisis_response_includes_hotlines_and_therapists(monkeypatch, crisis_db):
    from app import main as app_main

    app_main._LAST_THERAPIST_LOCATION_BY_SESSION.clear()

    client = TestClient(app)

    response = client.post("/chat", json={"message": "I want to die"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["risk_level"] == "crisis"
    assert payload.get("premium_cta") is None
    assert "112" in payload["coach_message"]
    assert "90101" in payload["coach_message"]
    assert "1177" in payload["coach_message"]
    assert "diagnosis" not in payload["coach_message"].lower()
    assert "prescription" not in payload["coach_message"].lower()
    assert "city or postcode" in payload["coach_message"].lower()
    assert payload.get("therapists") is None


def test_crisis_with_location_triggers_therapist_search(monkeypatch, crisis_db):
    captured: dict[str, object] = {}

    def stub_search_with_retries(self, *, location_text: str, radius_km: int | None, specialty: str | None):
        captured["location"] = location_text
        captured["radius_km"] = radius_km
        captured["specialty"] = specialty
        return (
            [
                {
                    "name": "Safe Steps Clinic",
                    "address": "1 Main St, Stockholm",
                    "url": "https://example.com/safe-steps",
                    "phone": "+46 8 100 100",
                    "distance_km": 4.2,
                }
            ],
            None,
        )

    monkeypatch.setattr(
        "app.agents.therapist_agent.TherapistSearchAgent.search_with_retries",
        stub_search_with_retries,
    )
    client = TestClient(app)
    original_dev_mode = settings.dev_mode
    settings.dev_mode = True
    try:
        response = client.post("/chat", json={"message": "I want to die near Stockholm within 10 km"})
    finally:
        settings.dev_mode = original_dev_mode

    assert response.status_code == 200
    payload = response.json()
    assert payload["risk_level"] == "crisis"
    assert payload.get("therapists")
    assert payload["therapists"][0]["name"] == "Safe Steps Clinic"
    assert captured["location"] == "Stockholm"
    assert captured["radius_km"] == 10


def test_crisis_response_reuses_last_session_location(monkeypatch, crisis_db):
    from app import main as app_main

    with db.SessionLocal() as session:
        user = User(email="crisis@example.com", name="Crisis User", is_premium=True)
        session.add(user)
        session.commit()
        session.refresh(user)

    app_main._LAST_THERAPIST_LOCATION_BY_SESSION.clear()
    app_main._LAST_THERAPIST_LOCATION_BY_SESSION[f"user:{user.id}"] = "Uppsala"
    captured: dict[str, object] = {}

    def stub_search_with_retries(self, *, location_text: str, radius_km: int | None, specialty: str | None):
        captured["location"] = location_text
        return ([], None)

    monkeypatch.setattr(
        "app.agents.therapist_agent.TherapistSearchAgent.search_with_retries",
        stub_search_with_retries,
    )
    client = TestClient(app)
    client.cookies.set(settings.session_cookie_name, str(user.id))

    response = client.post("/chat", json={"message": "I'm going to hurt myself"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["risk_level"] == "crisis"
    assert captured["location"] == "Uppsala"
