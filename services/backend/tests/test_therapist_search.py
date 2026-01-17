import pytest
from fastapi.testclient import TestClient
import httpx

from app import db
from app.main import app
from app.models import User
from app.therapist_search import clear_cache, search_therapists


class DummyResponse:
    def __init__(self, payload, status_code: int = 200):
        self._payload = payload
        self.status_code = status_code

    def raise_for_status(self) -> None:
        return None

    def json(self):
        return self._payload


@pytest.fixture(autouse=True)
def reset_therapist_cache():
    clear_cache()
    yield
    clear_cache()


def test_therapist_search_geocode_overpass_happy_path(monkeypatch):
    def fake_get(url, params, headers, timeout):
        return DummyResponse([{"lat": "59.3300", "lon": "18.0600"}])

    def fake_post(url, content, headers, timeout):
        return DummyResponse(
            {
                "elements": [
                    {
                        "type": "node",
                        "id": 1,
                        "lat": 59.331,
                        "lon": 18.061,
                        "tags": {
                            "name": "Calm Clinic",
                            "addr:street": "Main St",
                            "addr:housenumber": "1",
                            "addr:city": "Stockholm",
                            "website": "https://www.mindler.se",
                            "phone": "+46 8 123 000"
                        }
                    },
                    {
                        "type": "node",
                        "id": 2,
                        "lat": 59.350,
                        "lon": 18.100,
                        "tags": {"name": "Far Clinic", "addr:city": "Stockholm", "addr:country": "Sweden"}
                    }
                ]
            }
        )

    monkeypatch.setattr("app.therapist_search.httpx.get", fake_get)
    monkeypatch.setattr("app.therapist_search.httpx.post", fake_post)

    results = search_therapists("Stockholm", radius_km=5)

    assert len(results) == 2
    assert results[0].name == "Calm Clinic"
    assert results[0].address.startswith("Main St")
    assert "example.com" not in results[0].url
    assert results[0].url.startswith("https://")
    assert results[1].address == "Stockholm, Sweden"
    assert results[1].phone == "Phone unavailable"
    assert results[0].distance_km <= results[1].distance_km
    assert "your area" not in results[0].name.lower()


def test_therapist_search_no_results(monkeypatch):
    monkeypatch.setattr(
        "app.therapist_search.httpx.get",
        lambda *args, **kwargs: DummyResponse([{"lat": "59.3300", "lon": "18.0600"}])
    )
    monkeypatch.setattr(
        "app.therapist_search.httpx.post",
        lambda *args, **kwargs: DummyResponse({"elements": []})
    )

    results = search_therapists("Nowhere", radius_km=5)

    assert results == []


def test_therapist_search_timeout(monkeypatch):
    def fake_get(*args, **kwargs):
        raise httpx.ReadTimeout("timeout")

    monkeypatch.setattr("app.therapist_search.httpx.get", fake_get)

    results = search_therapists("Stockholm", radius_km=5)

    assert results == []


def test_therapist_search_geocode_failure_returns_empty(monkeypatch):
    monkeypatch.setattr("app.therapist_search.httpx.get", lambda *args, **kwargs: DummyResponse([]))

    def fail_post(*_args, **_kwargs):
        raise AssertionError("Overpass should not be called when geocode fails.")

    monkeypatch.setattr("app.therapist_search.httpx.post", fail_post)

    results = search_therapists("Unknown", radius_km=5)

    assert results == []


def test_therapist_search_overpass_timeout(monkeypatch):
    monkeypatch.setattr(
        "app.therapist_search.httpx.get",
        lambda *args, **kwargs: DummyResponse([{"lat": "59.3300", "lon": "18.0600"}])
    )

    def fake_post(*_args, **_kwargs):
        raise httpx.ReadTimeout("timeout")

    monkeypatch.setattr("app.therapist_search.httpx.post", fake_post)

    results = search_therapists("Stockholm", radius_km=5)

    assert results == []


def test_therapist_search_overpass_rate_limited(monkeypatch):
    monkeypatch.setattr(
        "app.therapist_search.httpx.get",
        lambda *args, **kwargs: DummyResponse([{"lat": "59.3300", "lon": "18.0600"}])
    )
    monkeypatch.setattr(
        "app.therapist_search.httpx.post",
        lambda *args, **kwargs: DummyResponse({"elements": []}, status_code=429)
    )

    results = search_therapists("Stockholm", radius_km=5)

    assert results == []


def test_premium_gating_therapist_search():
    original_db_url = str(db.engine.url)
    db.reset_engine("sqlite+pysqlite:///./test_therapist_gate.db")
    db.init_db()
    try:
        with db.SessionLocal() as session:
            session.query(User).delete()
            user = User(email="free@example.com", name="Free User", is_premium=False)
            session.add(user)
            session.commit()
            session.refresh(user)

        client = TestClient(app)
        client.cookies.set("mh_session", str(user.id))
        response = client.post("/therapists/search", json={"location": "Stockholm"})

        assert response.status_code == 403
    finally:
        db.reset_engine(original_db_url)


def test_premium_search_returns_results(monkeypatch):
    original_db_url = str(db.engine.url)
    db.reset_engine("sqlite+pysqlite:///./test_therapist_gate_premium.db")
    db.init_db()
    try:
        with db.SessionLocal() as session:
            session.query(User).delete()
            user = User(email="pro@example.com", name="Pro User", is_premium=True)
            session.add(user)
            session.commit()
            session.refresh(user)

        monkeypatch.setattr(
            "app.main.search_therapists",
            lambda *_args, **_kwargs: [
                {
                    "name": "Mindler",
                    "address": "Stockholm",
                    "url": "https://www.mindler.se",
                    "phone": "",
                    "distance_km": 1.0
                }
            ]
        )
        client = TestClient(app)
        client.cookies.set("mh_session", str(user.id))
        response = client.post("/therapists/search", json={"location": "Stockholm"})

        assert response.status_code == 200
        payload = response.json()
        assert payload["results"][0]["name"] == "Mindler"
    finally:
        db.reset_engine(original_db_url)
