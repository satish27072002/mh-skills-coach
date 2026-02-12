import httpx
import pytest

from app import mcp_client


class DummyResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def json(self):
        return self._payload


def test_mcp_send_email_success(monkeypatch):
    monkeypatch.setattr(
        mcp_client.httpx,
        "post",
        lambda *args, **kwargs: DummyResponse({"ok": True, "message_id": "<msg@example.com>"})
    )

    result = mcp_client.mcp_send_email(
        to="user@example.com",
        subject="Hi",
        body="Body"
    )

    assert result["ok"] is True
    assert result["message_id"] == "<msg@example.com>"


def test_mcp_send_email_timeout(monkeypatch):
    def timeout_post(*args, **kwargs):
        raise httpx.ReadTimeout("timeout")

    monkeypatch.setattr(mcp_client.httpx, "post", timeout_post)

    with pytest.raises(mcp_client.MCPClientError, match="timed out"):
        mcp_client.mcp_send_email(to="user@example.com", subject="Hi", body="Body")


def test_mcp_send_email_error_payload(monkeypatch):
    monkeypatch.setattr(
        mcp_client.httpx,
        "post",
        lambda *args, **kwargs: DummyResponse(
            {
                "ok": False,
                "error": {
                    "code": "SMTP_ERROR",
                    "message": "smtp down",
                    "details": {}
                }
            },
            status_code=502
        )
    )

    with pytest.raises(mcp_client.MCPClientError, match="SMTP_ERROR"):
        mcp_client.mcp_send_email(to="user@example.com", subject="Hi", body="Body")
