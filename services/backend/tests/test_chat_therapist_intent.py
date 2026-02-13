import pytest
from fastapi.testclient import TestClient

from app import db, mcp_client
from app.config import settings
from app.main import app
from app.models import PendingAction, User


ORIGINAL_DATABASE_URL = str(db.engine.url)


def _reset_db() -> None:
    db.reset_engine("sqlite+pysqlite:///./test_chat_therapist_intent.db")
    db.init_db()
    with db.SessionLocal() as session:
        session.query(PendingAction).delete()
        session.query(User).delete()
        session.commit()


@pytest.fixture()
def therapist_chat_db():
    _reset_db()
    from app.agents import therapist_agent

    therapist_agent.LAST_THERAPIST_LOCATION_BY_SESSION.clear()
    therapist_agent.PENDING_THERAPIST_QUERY_BY_SESSION.clear()
    yield
    db.reset_engine(ORIGINAL_DATABASE_URL)
    therapist_agent.LAST_THERAPIST_LOCATION_BY_SESSION.clear()
    therapist_agent.PENDING_THERAPIST_QUERY_BY_SESSION.clear()


def test_chat_find_therapist_routes_to_search_not_booking(monkeypatch, therapist_chat_db):
    with db.SessionLocal() as session:
        user = User(email="premium-chat@example.com", name="Premium Chat", is_premium=True)
        session.add(user)
        session.commit()
        session.refresh(user)

    captured: dict[str, object] = {}

    def stub_search_with_retries(
        self,
        *,
        location_text: str,
        radius_km: int | None,
        specialty: str | None,
        limit: int | None = None,
    ):
        captured["location"] = location_text
        captured["radius_km"] = radius_km
        captured["specialty"] = specialty
        captured["limit"] = limit
        return (
            [
                {
                    "name": "Stockholm Therapy",
                    "address": "2 Main St, Stockholm",
                    "url": "https://example.com/stockholm-therapy",
                    "phone": "+46 8 111 111",
                    "distance_km": 3.1,
                }
            ],
            None,
        )

    monkeypatch.setattr(
        "app.agents.therapist_agent.TherapistSearchAgent.search_with_retries",
        stub_search_with_retries,
    )
    client = TestClient(app)
    client.cookies.set(settings.session_cookie_name, str(user.id))

    response = client.post("/chat", json={"message": "Find therapists near Stockholm within 10 km"})

    assert response.status_code == 200
    payload = response.json()
    assert payload.get("therapists")
    assert payload.get("booking_proposal") is None
    assert payload.get("requires_confirmation") is not True
    assert "date/time" not in payload["coach_message"].lower()
    assert captured["location"] == "Stockholm"
    assert captured["radius_km"] == 10
    assert captured["limit"] == 10


def test_chat_therapist_search_works_for_free_user_in_dev_mode(monkeypatch, therapist_chat_db):
    with db.SessionLocal() as session:
        user = User(email="free-dev@example.com", name="Free Dev", is_premium=False)
        session.add(user)
        session.commit()
        session.refresh(user)

    monkeypatch.setattr(
        "app.agents.therapist_agent.TherapistSearchAgent.search_with_retries",
        lambda self, **kwargs: (
            [
                {
                    "name": "Dev Clinic",
                    "address": "3 Main St, Stockholm",
                    "url": "https://example.com/dev-clinic",
                    "phone": "+46 8 222 222",
                    "distance_km": 2.0,
                }
            ],
            None,
        ),
    )
    client = TestClient(app)
    client.cookies.set(settings.session_cookie_name, str(user.id))

    original_dev_mode = settings.dev_mode
    settings.dev_mode = True
    try:
        response = client.post("/chat", json={"message": "find therapist in Stockholm"})
    finally:
        settings.dev_mode = original_dev_mode

    assert response.status_code == 200
    payload = response.json()
    assert payload.get("therapists")
    assert payload.get("premium_cta") is None


def test_chat_therapist_search_omits_specialty_when_not_provided(monkeypatch, therapist_chat_db):
    with db.SessionLocal() as session:
        user = User(email="premium-payload@example.com", name="Premium Payload", is_premium=True)
        session.add(user)
        session.commit()
        session.refresh(user)

    captured: dict[str, object] = {}

    class DummyResponse:
        status_code = 200

        @staticmethod
        def json():
            return {
                "ok": True,
                "results": [
                    {
                        "name": "Payload Clinic",
                        "address": "4 Main St, Stockholm",
                        "distance_km": 2.2,
                        "phone": "+46 8 333 333",
                        "email": None,
                        "source_url": "https://example.com/payload",
                    }
                ],
            }

    def capture_post(*args, **kwargs):
        captured["json"] = kwargs.get("json")
        return DummyResponse()

    monkeypatch.setattr(mcp_client.httpx, "post", capture_post)
    client = TestClient(app)
    client.cookies.set(settings.session_cookie_name, str(user.id))

    response = client.post("/chat", json={"message": "Find therapists near Stockholm within 10 km"})

    assert response.status_code == 200
    payload = response.json()
    assert payload.get("therapists")
    outbound = captured.get("json")
    assert isinstance(outbound, dict)
    assert outbound["location_text"] == "Stockholm"
    assert outbound["radius_km"] == 10
    assert outbound["limit"] == 10
    assert "specialty" not in outbound


def test_chat_multiturn_asks_location_then_uses_city_reply(monkeypatch, therapist_chat_db):
    captured: dict[str, object] = {}

    monkeypatch.setattr(
        "app.agents.therapist_agent.TherapistSearchAgent.search_with_retries",
        lambda self, **kwargs: (
            [
                {
                    "name": "City Reply Clinic",
                    "address": "5 Main St, Stockholm",
                    "url": "https://example.com/city-reply",
                    "phone": "+46 8 444 444",
                    "distance_km": 3.3,
                }
            ],
            None,
        ),
    )

    original_dev_mode = settings.dev_mode
    settings.dev_mode = True
    try:
        client = TestClient(app)
        first = client.post("/chat", json={"message": "help me find a therapist"})
        assert first.status_code == 200
        assert first.json()["coach_message"] == "Please share a city or postcode so I can search nearby providers."

        def capture_search(self, *, location_text: str, radius_km: int | None, specialty: str | None, limit: int | None = None):
            captured["location"] = location_text
            captured["radius"] = radius_km
            return (
                [
                    {
                        "name": "City Reply Clinic",
                        "address": "5 Main St, Stockholm",
                        "url": "https://example.com/city-reply",
                        "phone": "+46 8 444 444",
                        "distance_km": 3.3,
                    }
                ],
                None,
            )

        monkeypatch.setattr(
            "app.agents.therapist_agent.TherapistSearchAgent.search_with_retries",
            capture_search,
        )
        second = client.post("/chat", json={"message": "stockholm"})
    finally:
        settings.dev_mode = original_dev_mode

    assert second.status_code == 200
    payload = second.json()
    assert payload.get("therapists")
    assert captured["location"] == "stockholm"
    assert captured["radius"] == 25


def test_chat_therapist_search_dev_mode_bypass_without_auth(monkeypatch, therapist_chat_db):
    monkeypatch.setattr(
        "app.agents.therapist_agent.TherapistSearchAgent.search_with_retries",
        lambda self, **kwargs: (
            [
                {
                    "name": "No Auth Clinic",
                    "address": "6 Main St, Stockholm",
                    "url": "https://example.com/no-auth",
                    "phone": "+46 8 555 555",
                    "distance_km": 1.5,
                }
            ],
            None,
        ),
    )

    original_dev_mode = settings.dev_mode
    settings.dev_mode = True
    try:
        client = TestClient(app)
        response = client.post("/chat", json={"message": "find therapist near Stockholm"})
    finally:
        settings.dev_mode = original_dev_mode

    assert response.status_code == 200
    payload = response.json()
    assert payload.get("therapists")
    assert payload.get("premium_cta") is None


def test_successful_search_then_missing_location_does_not_reuse_previous_city(monkeypatch, therapist_chat_db):
    with db.SessionLocal() as session:
        user = User(email="state@example.com", name="State User", is_premium=True)
        session.add(user)
        session.commit()
        session.refresh(user)

    calls: list[dict[str, object]] = []

    def capture_search(
        self,
        *,
        location_text: str,
        radius_km: int | None,
        specialty: str | None,
        limit: int | None = None,
    ):
        calls.append(
            {
                "location_text": location_text,
                "radius_km": radius_km,
                "specialty": specialty,
                "limit": limit,
            }
        )
        return (
            [
                {
                    "name": "Sticky Clinic",
                    "address": "7 Main St, Stockholm",
                    "url": "https://example.com/sticky",
                    "phone": "+46 8 666 666",
                    "distance_km": 1.2,
                }
            ],
            None,
        )

    monkeypatch.setattr(
        "app.agents.therapist_agent.TherapistSearchAgent.search_with_retries",
        capture_search,
    )
    client = TestClient(app)
    client.cookies.set(settings.session_cookie_name, str(user.id))

    first = client.post("/chat", json={"message": "find therapists near Stockholm within 25 km"})
    assert first.status_code == 200
    assert first.json().get("therapists")
    assert calls[0]["location_text"] == "Stockholm"

    second = client.post("/chat", json={"message": "help me find a therapist"})
    assert second.status_code == 200
    second_payload = second.json()
    assert second_payload["coach_message"] == "Please share a city or postcode so I can search nearby providers."
    assert second_payload.get("therapists") == []
    # No extra MCP/agent search call for the missing-location follow-up turn.
    assert len(calls) == 1
