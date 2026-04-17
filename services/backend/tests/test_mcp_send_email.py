import pytest

from app import mcp_client


def test_mcp_send_email_success(monkeypatch):
    async def invoke_stub(tool_suffix, payload):
        assert tool_suffix == "send_email_tool"
        assert payload["to"] == "user@example.com"
        return {"message_id": "<msg@example.com>"}

    monkeypatch.setattr(mcp_client, "ainvoke_mcp_tool", invoke_stub)

    result = mcp_client.mcp_send_email(
        to="user@example.com",
        subject="Hi",
        body="Body"
    )

    assert result["ok"] is True
    assert result["message_id"] == "<msg@example.com>"


def test_mcp_send_email_timeout(monkeypatch):
    async def timeout_tool(*args, **kwargs):
        raise mcp_client.httpx.ReadTimeout("timeout")

    monkeypatch.setattr(mcp_client, "ainvoke_mcp_tool", timeout_tool)

    with pytest.raises(mcp_client.MCPClientError, match="timed out"):
        mcp_client.mcp_send_email(to="user@example.com", subject="Hi", body="Body")


def test_mcp_send_email_error_payload(monkeypatch):
    async def bad_tool(*args, **kwargs):
        raise RuntimeError("SMTP_ERROR: smtp down")

    monkeypatch.setattr(mcp_client, "ainvoke_mcp_tool", bad_tool)

    with pytest.raises(mcp_client.MCPClientError, match="SMTP_ERROR"):
        mcp_client.mcp_send_email(to="user@example.com", subject="Hi", body="Body")
