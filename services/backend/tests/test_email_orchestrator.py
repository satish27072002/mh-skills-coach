import pytest
from fastapi import HTTPException

from app import db
from app.email_orchestrator import EmailSendPayload, send_email_for_user
from app.mcp_client import MCPClientError
from app.models import OutboundEmail


ORIGINAL_DATABASE_URL = str(db.engine.url)


@pytest.fixture()
def email_db():
    db.reset_engine("sqlite+pysqlite:///./test_email_orchestrator.db")
    db.init_db()
    with db.SessionLocal() as session:
        session.query(OutboundEmail).delete()
        session.commit()
    yield
    db.reset_engine(ORIGINAL_DATABASE_URL)


def test_rate_limit_blocks_fourth_attempt(monkeypatch, email_db):
    monkeypatch.setattr(
        "app.email_orchestrator.mcp_send_email",
        lambda **kwargs: {"ok": True, "message_id": "<msg-1@example.com>"}
    )
    payload = EmailSendPayload(
        to="user@example.com",
        subject="Hello",
        body="Message body"
    )

    send_email_for_user("42", payload)
    send_email_for_user("42", payload)
    send_email_for_user("42", payload)

    with pytest.raises(HTTPException) as exc:
        send_email_for_user("42", payload)

    assert exc.value.status_code == 429
    with db.SessionLocal() as session:
        rows = session.query(OutboundEmail).all()
        statuses = [row.status for row in rows]
        assert statuses.count("sent") == 3
        assert statuses.count("blocked") == 1


def test_success_logs_sent(monkeypatch, email_db):
    monkeypatch.setattr(
        "app.email_orchestrator.mcp_send_email",
        lambda **kwargs: {"ok": True, "message_id": "<msg-2@example.com>"}
    )
    payload = EmailSendPayload(
        to="user@example.com",
        subject="Subject",
        body="Body"
    )

    result = send_email_for_user("7", payload)

    assert result["ok"] is True
    with db.SessionLocal() as session:
        row = session.query(OutboundEmail).filter(OutboundEmail.user_id == "7").one()
        assert row.status == "sent"
        assert row.error is None


def test_mcp_error_logs_failed_and_returns_502(monkeypatch, email_db):
    def fail_send(**kwargs):
        raise MCPClientError("smtp unavailable")

    monkeypatch.setattr("app.email_orchestrator.mcp_send_email", fail_send)
    payload = EmailSendPayload(
        to="user@example.com",
        subject="Subject",
        body="Body"
    )

    with pytest.raises(HTTPException) as exc:
        send_email_for_user("9", payload)

    assert exc.value.status_code == 502
    with db.SessionLocal() as session:
        row = session.query(OutboundEmail).filter(OutboundEmail.user_id == "9").one()
        assert row.status == "failed"
        assert "smtp unavailable" in (row.error or "")


def test_dev_mode_blocks_when_smtp_not_configured(monkeypatch, email_db):
    monkeypatch.setattr("app.email_orchestrator.settings.dev_mode", True)
    monkeypatch.delenv("SMTP_HOST", raising=False)
    monkeypatch.delenv("SMTP_FROM", raising=False)
    payload = EmailSendPayload(
        to="user@example.com",
        subject="Subject",
        body="Body"
    )

    with pytest.raises(HTTPException) as exc:
        send_email_for_user("11", payload)

    assert exc.value.status_code == 503
    assert "SMTP not configured" in str(exc.value.detail)
    with db.SessionLocal() as session:
        row = session.query(OutboundEmail).filter(OutboundEmail.user_id == "11").one()
        assert row.status == "blocked"
        assert row.error == "smtp_not_configured"
