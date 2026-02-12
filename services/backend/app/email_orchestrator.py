from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import HTTPException
from sqlalchemy import func, select

from . import db
from .mcp_client import MCPClientError, mcp_send_email
from .models import OutboundEmail


MAX_EMAIL_ATTEMPTS_PER_24H = 3
EMAIL_WINDOW_HOURS = 24


@dataclass
class EmailSendPayload:
    to: str
    subject: str
    body: str
    reply_to: str | None = None


def _log_attempt(
    *,
    user_id: str,
    to_email: str,
    subject: str,
    status: str,
    error: str | None = None
) -> None:
    with db.SessionLocal() as session:
        session.add(
            OutboundEmail(
                user_id=user_id,
                to_email=to_email,
                subject=subject,
                status=status,
                error=error
            )
        )
        session.commit()


def _attempt_count_last_24h(user_id: str) -> int:
    cutoff = datetime.now(timezone.utc) - timedelta(hours=EMAIL_WINDOW_HOURS)
    with db.SessionLocal() as session:
        count = session.execute(
            select(func.count(OutboundEmail.id)).where(
                OutboundEmail.user_id == user_id,
                OutboundEmail.created_at >= cutoff,
                OutboundEmail.status.in_(("sent", "failed"))
            )
        ).scalar_one()
    return int(count)


def send_email_for_user(user_id: str, payload: EmailSendPayload) -> dict[str, Any]:
    user_key = str(user_id)
    attempts = _attempt_count_last_24h(user_key)
    if attempts >= MAX_EMAIL_ATTEMPTS_PER_24H:
        _log_attempt(
            user_id=user_key,
            to_email=payload.to,
            subject=payload.subject,
            status="blocked",
            error="rate_limit_exceeded"
        )
        raise HTTPException(
            status_code=429,
            detail="Email rate limit exceeded (max 3 attempts per 24 hours)."
        )

    try:
        result = mcp_send_email(
            to=payload.to,
            subject=payload.subject,
            body=payload.body,
            reply_to=payload.reply_to
        )
    except MCPClientError as exc:
        _log_attempt(
            user_id=user_key,
            to_email=payload.to,
            subject=payload.subject,
            status="failed",
            error=str(exc)
        )
        raise HTTPException(status_code=502, detail="Failed to send email via MCP.") from exc

    _log_attempt(
        user_id=user_key,
        to_email=payload.to,
        subject=payload.subject,
        status="sent"
    )
    return result
