import logging

from fastapi import Response

from app.config import settings
import app.main as main


def test_cookie_samesite_none_forces_secure(monkeypatch, caplog):
    monkeypatch.setattr(settings, "cookie_samesite", "none")
    monkeypatch.setattr(settings, "cookie_secure", False)
    response = Response()

    with caplog.at_level(logging.WARNING):
        main._set_cookie(response, settings.session_cookie_name, "123")

    set_cookie = response.headers.get("set-cookie", "").lower()
    assert "samesite=none" in set_cookie
    assert "secure" in set_cookie
    assert any(
        "COOKIE_SAMESITE=None requires COOKIE_SECURE=true" in record.message
        for record in caplog.records
    )
