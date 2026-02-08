import pytest
from fastapi.testclient import TestClient

from app import db
from app.config import settings
from app.main import app
from app.models import User
from app.schemas import TherapistResult


ORIGINAL_DATABASE_URL = str(db.engine.url)


def _reset_db():
    db.reset_engine("sqlite+pysqlite:///./test_therapists.db")
    db.init_db()
    with db.SessionLocal() as session:
        session.query(User).delete()
        session.commit()


@pytest.fixture()
def test_db():
    _reset_db()
    yield
    db.reset_engine(ORIGINAL_DATABASE_URL)


def test_therapist_search_requires_premium(test_db):
    client = TestClient(app)

    response = client.post("/chat", json={"message": "find therapist near me"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["premium_cta"]["enabled"] is True
    assert payload.get("resources") is None
    assert payload.get("therapists") is None


def test_therapist_search_returns_results_for_premium(monkeypatch, test_db):
    with db.SessionLocal() as session:
        user = User(email="premium@example.com", name="Premium User", is_premium=True)
        session.add(user)
        session.commit()
        session.refresh(user)

    def stub_search(_location, _radius):
        return [
            TherapistResult(
                name="Stockholm Therapy",
                address="1 Main St, Stockholm",
                url="https://example.com/therapy",
                phone="+46 8 000 000",
                distance_km=2.4
            )
        ]

    monkeypatch.setattr("app.main.search_therapists", stub_search)
    client = TestClient(app)
    client.cookies.set(settings.session_cookie_name, str(user.id))

    response = client.post("/chat", json={"message": "find therapist in Stockholm"})

    assert response.status_code == 200
    payload = response.json()
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
