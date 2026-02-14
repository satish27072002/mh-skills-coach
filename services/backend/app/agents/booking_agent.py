from __future__ import annotations

import re
import logging
from datetime import datetime
from typing import Any, Callable
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.booking import (
    BOOKING_TTL_MINUTES,
    STOCKHOLM_TZ,
    build_booking_email_content,
    clear_pending_booking,
    extract_booking_data,
    is_affirmative,
    is_booking_intent,
    is_negative,
    load_pending_booking,
    parse_pending_payload,
    save_pending_booking,
)
from app.email_orchestrator import EmailSendPayload
from app.models import PendingAction, User
from app.prompts import BOOKING_EMAIL_MASTER_PROMPT
from app.schemas import BookingProposal, ChatResponse

UTC = ZoneInfo("UTC")
logger = logging.getLogger(__name__)
SYSTEM_PROMPT = BOOKING_EMAIL_MASTER_PROMPT


def is_confirmation_only_message(message: str) -> bool:
    tokens = re.sub(r"[^a-z]+", " ", message.lower()).strip().split()
    if not tokens:
        return False
    allowed = {"yes", "confirm", "confirmed", "ok", "okay", "y"}
    return all(token in allowed for token in tokens)


def _pending_payload_complete(payload: dict[str, str | None]) -> bool:
    return bool(
        payload.get("therapist_email")
        and payload.get("requested_datetime_iso")
        and payload.get("subject")
        and payload.get("body")
    )


def _missing_payload_fields(payload: dict[str, Any]) -> list[str]:
    missing: list[str] = []
    if not payload.get("therapist_email"):
        missing.append("therapist_email")
    if not payload.get("requested_datetime_iso"):
        missing.append("requested_datetime_iso")
    return missing


def _stamp_payload_state(payload: dict[str, Any]) -> dict[str, Any]:
    payload["timezone"] = "Europe/Stockholm"
    payload["missing_fields"] = _missing_payload_fields(payload)
    return payload


def _requested_time_display(requested_datetime_iso: str) -> str:
    parsed = datetime.fromisoformat(requested_datetime_iso)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=STOCKHOLM_TZ)
    else:
        parsed = parsed.astimezone(STOCKHOLM_TZ)
    return f"{parsed.strftime('%Y-%m-%d %H:%M')} Europe/Stockholm"


def _booking_proposal_from_payload(payload: dict[str, str | None], expires_at: datetime) -> BookingProposal:
    requested_datetime_iso = payload.get("requested_datetime_iso") or ""
    expires_display_dt = (
        expires_at.astimezone(STOCKHOLM_TZ)
        if expires_at.tzinfo
        else expires_at.replace(tzinfo=UTC).astimezone(STOCKHOLM_TZ)
    )
    return BookingProposal(
        therapist_email=payload.get("therapist_email") or "",
        requested_time=_requested_time_display(requested_datetime_iso),
        subject=payload.get("subject") or "",
        body=payload.get("body") or "",
        expires_at=expires_display_dt.isoformat(),
    )


def _missing_booking_fields_message(
    payload: dict[str, str | None],
    clarification: str | None = None,
) -> str:
    missing = []
    if not payload.get("therapist_email"):
        missing.append("therapist email")
    if not payload.get("requested_datetime_iso"):
        missing.append("appointment date and time")
    if clarification:
        return clarification
    if len(missing) == 2:
        return (
            "Please share the therapist email and requested date/time in Europe/Stockholm "
            "(for example: therapist@example.com, 2026-02-14 15:00)."
        )
    if "therapist email" in missing:
        return "Please provide the therapist email address."
    return "Please provide the requested appointment date/time in Europe/Stockholm."


class BookingEmailAgent:
    def __init__(self, *, send_email_fn: Callable[[str, EmailSendPayload], dict[str, Any]]):
        self._send_email_fn = send_email_fn

    def handle(
        self,
        *,
        db: Session,
        user: User | None,
        actor_key: str,
        message: str,
        pending_action: PendingAction | None,
        pending_expired: bool,
    ) -> ChatResponse | None:
        if pending_action:
            pending_payload = parse_pending_payload(pending_action)
            if is_negative(message):
                clear_pending_booking(db, pending_action)
                logger.info("booking_pending_cancelled actor_key=%s", actor_key)
                return ChatResponse(
                    coach_message="Okay, I cancelled the pending booking email request.",
                    requires_confirmation=False,
                )

            if is_affirmative(message):
                if not _pending_payload_complete(pending_payload):
                    return ChatResponse(coach_message=_missing_booking_fields_message(pending_payload))
                email_payload = EmailSendPayload(
                    to=pending_payload["therapist_email"] or "",
                    subject=pending_payload["subject"] or "",
                    body=pending_payload["body"] or "",
                    reply_to=pending_payload.get("reply_to"),
                )
                try:
                    self._send_email_fn(actor_key, email_payload)
                    coach_message = "Email sent successfully. I have cleared the pending booking request."
                    logger.info("booking_email_sent actor_key=%s to=%s", actor_key, email_payload.to)
                except HTTPException as exc:
                    coach_message = f"I could not send the email: {exc.detail}"
                    logger.info("booking_email_failed actor_key=%s reason=%s", actor_key, exc.detail)
                clear_pending_booking(db, pending_action)
                return ChatResponse(
                    coach_message=coach_message,
                    requires_confirmation=False,
                )

            update = extract_booking_data(message)
            changed = False
            if not pending_payload.get("therapist_email") and update.therapist_email:
                pending_payload["therapist_email"] = update.therapist_email
                changed = True
            if not pending_payload.get("requested_datetime_iso") and update.requested_datetime:
                pending_payload["requested_datetime_iso"] = update.requested_datetime.isoformat()
                changed = True

            if _pending_payload_complete(pending_payload):
                proposal = _booking_proposal_from_payload(pending_payload, pending_action.expires_at)
                logger.info("booking_proposal_ready actor_key=%s to=%s", actor_key, proposal.therapist_email)
                return ChatResponse(
                    coach_message=(
                        f"Please confirm sending this request to {proposal.therapist_email} for "
                        f"{proposal.requested_time}. Reply YES to send or NO to cancel."
                    ),
                    booking_proposal=proposal,
                    requires_confirmation=True,
                )

            if changed and pending_payload.get("therapist_email") and pending_payload.get("requested_datetime_iso"):
                dt = datetime.fromisoformat(pending_payload["requested_datetime_iso"] or "")
                complete_payload = build_booking_email_content(
                    user=user,
                    therapist_email=pending_payload["therapist_email"] or "",
                    requested_datetime=dt,
                    sender_name=pending_payload.get("sender_name"),
                    sender_email=pending_payload.get("reply_to"),
                )
                save_pending_booking(db, actor_key, _stamp_payload_state(complete_payload))
                refreshed_action, _ = load_pending_booking(db, actor_key)
                if not refreshed_action:
                    raise HTTPException(status_code=500, detail="failed to load pending booking")
                refreshed_payload = parse_pending_payload(refreshed_action)
                proposal = _booking_proposal_from_payload(refreshed_payload, refreshed_action.expires_at)
                logger.info("booking_proposal_created actor_key=%s to=%s", actor_key, proposal.therapist_email)
                return ChatResponse(
                    coach_message=(
                        f"I prepared the email to {proposal.therapist_email} for {proposal.requested_time}. "
                        "Reply YES to send or NO to cancel."
                    ),
                    booking_proposal=proposal,
                    requires_confirmation=True,
                )

            if changed:
                save_pending_booking(db, actor_key, _stamp_payload_state(pending_payload))
                logger.info(
                    "booking_pending_updated actor_key=%s missing=%s",
                    actor_key,
                    ",".join(_missing_payload_fields(pending_payload)),
                )

            return ChatResponse(
                coach_message=_missing_booking_fields_message(pending_payload, clarification=update.clarification)
            )

        if pending_expired and (is_affirmative(message) or is_negative(message)):
            logger.info("booking_pending_expired actor_key=%s", actor_key)
            return ChatResponse(
                coach_message=(
                    f"Your pending booking request expired after {BOOKING_TTL_MINUTES} minutes. "
                    "Please start again with therapist email and time."
                ),
                requires_confirmation=False,
            )

        if is_confirmation_only_message(message):
            return ChatResponse(
                coach_message="No pending booking request to confirm. Please provide therapist email + time.",
                requires_confirmation=False,
            )

        if not is_booking_intent(message):
            return None

        extracted = extract_booking_data(message)
        booking_payload: dict[str, Any] = {
            "therapist_email": extracted.therapist_email,
            "requested_datetime_iso": extracted.requested_datetime.isoformat() if extracted.requested_datetime else None,
            "subject": None,
            "body": None,
            "reply_to": user.email if user and user.email else None,
            "sender_name": extracted.sender_name or (user.name if user and user.name else None),
        }

        if extracted.therapist_email and extracted.requested_datetime:
            booking_payload = build_booking_email_content(
                user=user,
                therapist_email=extracted.therapist_email,
                requested_datetime=extracted.requested_datetime,
                sender_name=extracted.sender_name,
            )
            pending = save_pending_booking(db, actor_key, _stamp_payload_state(booking_payload))
            proposal = _booking_proposal_from_payload(booking_payload, pending.expires_at)
            logger.info("booking_proposal_created actor_key=%s to=%s", actor_key, proposal.therapist_email)
            return ChatResponse(
                coach_message=(
                    f"I prepared an appointment email to {proposal.therapist_email} for "
                    f"{proposal.requested_time}. Reply YES to send or NO to cancel."
                ),
                booking_proposal=proposal,
                requires_confirmation=True,
            )

        save_pending_booking(db, actor_key, _stamp_payload_state(booking_payload))
        logger.info(
            "booking_pending_created actor_key=%s missing=%s",
            actor_key,
            ",".join(_missing_payload_fields(booking_payload)),
        )
        return ChatResponse(
            coach_message=_missing_booking_fields_message(booking_payload, clarification=extracted.clarification),
            requires_confirmation=False,
        )
