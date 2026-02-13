import httpx
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app import db, mcp_client
from app.config import settings
from app.main import app
from app.models import User


ORIGINAL_DATABASE_URL = str(db.engine.url)


class DummyResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def json(self):
        return self._payload


@pytest.fixture()
def test_db():
    db.reset_engine("sqlite+pysqlite:///./test_therapist_mcp.db")
    db.init_db()
    with db.SessionLocal() as session:
        session.query(User).delete()
        session.commit()
    yield
    db.reset_engine(ORIGINAL_DATABASE_URL)


def _create_user(*, is_premium: bool) -> User:
    with db.SessionLocal() as session:
        user = User(email=f"user-{is_premium}@example.com", name="User", is_premium=is_premium)
        session.add(user)
        session.commit()
        session.refresh(user)
        return user


def test_mcp_therapist_search_success(monkeypatch):
    monkeypatch.setattr(
        mcp_client.httpx,
        "post",
        lambda *args, **kwargs: DummyResponse(
            {
                "ok": True,
                "results": [
                    {
                        "name": "Calm Clinic",
                        "address": "1 Main St",
                        "distance_km": 1.1,
                        "phone": "+46 8 123 000",
                        "email": None,
                        "source_url": "https://example.com/clinic"
                    }
                ]
            }
        )
    )

    results = mcp_client.mcp_therapist_search("Stockholm", radius_km=5, specialty=None, limit=5)

    assert len(results) == 1
    assert results[0].name == "Calm Clinic"
    assert results[0].url == "https://example.com/clinic"


def test_mcp_therapist_search_omits_empty_specialty(monkeypatch):
    captured: dict[str, object] = {}

    def capture_post(*args, **kwargs):
        captured["json"] = kwargs.get("json")
        return DummyResponse({"ok": True, "results": []})

    monkeypatch.setattr(mcp_client.httpx, "post", capture_post)

    mcp_client.mcp_therapist_search("Stockholm", radius_km=5, specialty="", limit=5)

    payload = captured["json"]
    assert isinstance(payload, dict)
    assert "specialty" not in payload


def test_mcp_therapist_search_omits_none_specialty(monkeypatch):
    captured: dict[str, object] = {}

    def capture_post(*args, **kwargs):
        captured["json"] = kwargs.get("json")
        return DummyResponse({"ok": True, "results": []})

    monkeypatch.setattr(mcp_client.httpx, "post", capture_post)

    mcp_client.mcp_therapist_search("Stockholm", radius_km=5, specialty=None, limit=5)

    payload = captured["json"]
    assert isinstance(payload, dict)
    assert "specialty" not in payload


def test_mcp_therapist_search_invalid_argument_schema(monkeypatch):
    monkeypatch.setattr(
        mcp_client.httpx,
        "post",
        lambda *args, **kwargs: DummyResponse(
            {"ok": True, "results": [{"name": "only_name"}]},
            status_code=200
        )
    )

    with pytest.raises(HTTPException) as exc:
        mcp_client.mcp_therapist_search("Stockholm")
    assert exc.value.status_code == 502
    assert "invalid mcp therapist_search payload" in str(exc.value.detail)


def test_mcp_therapist_search_invalid_argument_error_payload(monkeypatch):
    monkeypatch.setattr(
        mcp_client.httpx,
        "post",
        lambda *args, **kwargs: DummyResponse(
            {
                "ok": False,
                "error": {
                    "code": "INVALID_ARGUMENT",
                    "message": "location_text is required",
                    "details": {}
                }
            },
            status_code=400
        )
    )

    with pytest.raises(HTTPException) as exc:
        mcp_client.mcp_therapist_search("Stockholm")
    assert exc.value.status_code == 502
    assert "INVALID_ARGUMENT" in str(exc.value.detail)


def test_therapists_route_mcp_timeout_returns_502(monkeypatch, test_db):
    premium_user = _create_user(is_premium=True)
    client = TestClient(app)
    client.cookies.set(settings.session_cookie_name, str(premium_user.id))

    def timeout_post(*args, **kwargs):
        raise httpx.ReadTimeout("timeout")

    monkeypatch.setattr(mcp_client.httpx, "post", timeout_post)

    response = client.post("/therapists/search", json={"location": "Stockholm", "radius_km": 5})

    assert response.status_code == 502
    assert "timed out" in response.json()["detail"].lower()


def test_premium_gating_therapist_search(test_db):
    free_user = _create_user(is_premium=False)
    client = TestClient(app)
    client.cookies.set(settings.session_cookie_name, str(free_user.id))

    response = client.post("/therapists/search", json={"location": "Stockholm"})

    assert response.status_code == 403


def test_therapists_route_accepts_location_text_alias(monkeypatch, test_db):
    premium_user = _create_user(is_premium=True)
    client = TestClient(app)
    client.cookies.set(settings.session_cookie_name, str(premium_user.id))

    monkeypatch.setattr(
        "app.main._run_therapist_search",
        lambda *args, **kwargs: []
    )

    response = client.post("/therapists/search", json={"location_text": "Stockholm", "radius_km": 10})

    assert response.status_code == 200
    assert response.json() == {"results": []}
