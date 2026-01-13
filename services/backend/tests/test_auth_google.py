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

    response = client.get(
        "/auth/google/callback?code=abc&state=bad",
        cookies={"oauth_state": "good", "pkce_verifier": "ver"}
    )

    assert response.status_code == 400


def test_missing_pkce_returns_400(monkeypatch):
    monkeypatch.setattr(settings, "google_client_id", None)
    monkeypatch.setattr(settings, "google_client_secret", None)
    client = TestClient(app)

    response = client.get(
        "/auth/google/callback?code=abc&state=ok",
        cookies={"oauth_state": "ok"}
    )

    assert response.status_code == 400


def test_stub_mode_sets_session_cookie(monkeypatch):
    monkeypatch.setattr(settings, "google_client_id", None)
    monkeypatch.setattr(settings, "google_client_secret", None)
    init_db()
    client = TestClient(app)

    response = client.get(
        "/auth/google/callback?code=abc&state=ok",
        cookies={"oauth_state": "ok", "pkce_verifier": "ver"}
    )

    assert response.status_code == 200
    assert response.json()["status"] == "stubbed"
    assert settings.session_cookie_name in response.cookies
