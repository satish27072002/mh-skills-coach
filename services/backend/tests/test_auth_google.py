import base64
import json
import logging
import os
from uuid import UUID

os.environ["DATABASE_URL"] = "sqlite+pysqlite:///./test.db"

from fastapi.testclient import TestClient

from app.config import settings
from app import db
from app.db import init_db
from app.main import app
import app.main as main
from app.models import User


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


def _encode_segment(payload: dict[str, object]) -> str:
    encoded = base64.urlsafe_b64encode(json.dumps(payload).encode("utf-8")).decode("ascii")
    return encoded.rstrip("=")


def test_id_token_invalid_logs_decoded_claims(monkeypatch, caplog):
    monkeypatch.setattr(settings, "google_client_id", "client-id")
    monkeypatch.setattr(settings, "google_client_secret", "client-secret")
    monkeypatch.setattr(settings, "frontend_url", "http://localhost:3000")

    header = _encode_segment({"alg": "RS256", "typ": "JWT"})
    payload = _encode_segment({
        "iss": "accounts.google.com",
        "aud": "client-id",
        "exp": 123456,
        "iat": 123000
    })
    fake_token = f"{header}.{payload}.sig"

    class DummyResponse:
        status_code = 200

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, str]:
            return {
                "access_token": "access",
                "id_token": fake_token,
                "token_type": "Bearer"
            }

    def fake_post(*_args, **_kwargs):
        return DummyResponse()

    def fake_verify(*_args, **_kwargs):
        raise ValueError("signature verification failed")

    monkeypatch.setattr(main.httpx, "post", fake_post)
    monkeypatch.setattr(main.google_id_token, "verify_oauth2_token", fake_verify)

    client = TestClient(app)
    client.cookies.set("oauth_state", "ok")
    client.cookies.set("pkce_verifier", "ver")

    with caplog.at_level(logging.WARNING):
        response = client.get("/auth/google/callback?code=abc&state=ok", follow_redirects=False)

    assert response.status_code == 302
    assert response.headers["location"].startswith(
        "http://localhost:3000/?auth_error=id_token_invalid"
    )
    assert any(
        "decoded_claims" in record.message and "accounts.google.com" in record.message
        for record in caplog.records
    )


def test_google_callback_upserts_by_google_sub_and_sets_session_cookie(monkeypatch):
    monkeypatch.setattr(settings, "google_client_id", "client-id")
    monkeypatch.setattr(settings, "google_client_secret", "client-secret")
    monkeypatch.setattr(settings, "frontend_url", "http://localhost:3000")
    init_db()

    token_payload = {
        "id_token": "id-token",
        "access_token": "access",
        "token_type": "Bearer"
    }

    monkeypatch.setattr(main, "_exchange_code_for_tokens", lambda *_args, **_kwargs: (token_payload, 200))
    monkeypatch.setattr(
        main,
        "_verify_id_token",
        lambda *_args, **_kwargs: {
            "sub": "google-sub-123",
            "email": "upsert@example.com",
            "name": "Upsert User"
        }
    )

    client = TestClient(app)
    client.cookies.set("oauth_state", "ok")
    client.cookies.set("pkce_verifier", "ver")

    first = client.get("/auth/google/callback?code=abc&state=ok", follow_redirects=False)
    assert first.status_code == 302
    assert settings.session_cookie_name in first.cookies
    first_cookie_value = first.cookies.get(settings.session_cookie_name)
    assert first_cookie_value is not None
    UUID(first_cookie_value)

    # Same google_sub should update existing user and keep same user id.
    second = client.get("/auth/google/callback?code=abc&state=ok", follow_redirects=False)
    assert second.status_code == 302
    assert second.cookies.get(settings.session_cookie_name) == first_cookie_value

    with db.SessionLocal() as session:
        users = session.query(User).filter(User.google_sub == "google-sub-123").all()
        assert len(users) == 1
        assert users[0].email == "upsert@example.com"
