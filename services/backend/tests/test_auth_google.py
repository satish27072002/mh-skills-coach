import os

os.environ["DATABASE_URL"] = "sqlite+pysqlite:///./test.db"

from fastapi.testclient import TestClient

from app.config import settings
from app.db import init_db
from app.main import app


def test_state_mismatch_returns_400(monkeypatch):
    monkeypatch.setattr(settings, "google_client_id", None)
    monkeypatch.setattr(settings, "google_client_secret", None)
    client = TestClient(app)

    client.cookies.set("oauth_state", "good")
    client.cookies.set("pkce_verifier", "ver")
    response = client.get("/auth/google/callback?code=abc&state=bad")

    assert response.status_code == 400


def test_missing_pkce_returns_400(monkeypatch):
    monkeypatch.setattr(settings, "google_client_id", None)
    monkeypatch.setattr(settings, "google_client_secret", None)
    client = TestClient(app)

    client.cookies.set("oauth_state", "ok")
    response = client.get("/auth/google/callback?code=abc&state=ok")

    assert response.status_code == 400


def test_stub_mode_sets_session_cookie(monkeypatch):
    monkeypatch.setattr(settings, "google_client_id", None)
    monkeypatch.setattr(settings, "google_client_secret", None)
    init_db()
    client = TestClient(app)

    client.cookies.set("oauth_state", "ok")
    client.cookies.set("pkce_verifier", "ver")
    response = client.get("/auth/google/callback?code=abc&state=ok")

    assert response.status_code == 200
    assert response.json()["status"] == "stubbed"
    assert settings.session_cookie_name in response.cookies


def test_access_denied_redirects(monkeypatch):
    monkeypatch.setattr(settings, "frontend_url", "http://localhost:3000")
    client = TestClient(app)

    response = client.get(
        "/auth/google/callback?error=access_denied&state=ignored",
        follow_redirects=False
    )

    assert response.status_code == 302
    assert response.headers["location"].startswith(
        "http://localhost:3000/?auth_error=access_denied"
    )
