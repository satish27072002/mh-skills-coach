from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from .models import PendingAction, User


BOOKING_ACTION_TYPE = "booking_email"
BOOKING_TTL_MINUTES = 15
STOCKHOLM_TZ = ZoneInfo("Europe/Stockholm")

EMAIL_RE = re.compile(r"([A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,})")
ISO_DATETIME_RE = re.compile(
    r"\b(\d{4}-\d{2}-\d{2}[T\s]\d{2}:\d{2}(?::\d{2})?(?:Z|[+-]\d{2}:\d{2})?)\b"
)
DATE_ONLY_RE = re.compile(r"\b(20\d{2}-\d{2}-\d{2})\b")
DATE_TIME_RE = re.compile(r"\b(\d{4}-\d{2}-\d{2})\s+(\d{1,2}:\d{2}(?:\s*[ap]m)?)\b", re.IGNORECASE)
TIME_RE = re.compile(r"\b(\d{1,2})(?::(\d{2}))?\s*([ap]m)?\b", re.IGNORECASE)
TIME_HHMM_RE = re.compile(r"\b([01]?\d|2[0-3]):([0-5]\d)\b")
DATE_TIME_WITH_AT_RE = re.compile(r"\b(20\d{2}-\d{2}-\d{2})\s+at\s+([01]?\d|2[0-3]):([0-5]\d)\b", re.IGNORECASE)
TIME_ON_DATE_RE = re.compile(r"\b([01]?\d|2[0-3]):([0-5]\d)\s+on\s+(20\d{2}-\d{2}-\d{2})\b", re.IGNORECASE)
ON_DATE_AT_TIME_RE = re.compile(r"\bon\s+(20\d{2}-\d{2}-\d{2})\s+at\s+([01]?\d|2[0-3]):([0-5]\d)\b", re.IGNORECASE)
NAME_RE = re.compile(
    r"\b(?:my name is|i am|i'm)\s+([a-z][a-z\s.'-]{1,60})\b",
    re.IGNORECASE,
)
WEEKDAY_RE = re.compile(
    r"\b(mon(?:day)?|tue(?:s|sday)?|wed(?:nesday)?|thu(?:rs|rsday)?|fri(?:day)?|sat(?:urday)?|sun(?:day)?)\b",
    re.IGNORECASE,
)

WEEKDAY_MAP = {
    "mon": 0,
    "monday": 0,
    "tue": 1,
    "tues": 1,
    "tuesday": 1,
    "wed": 2,
    "wednesday": 2,
    "thu": 3,
    "thur": 3,
    "thurs": 3,
    "thursday": 3,
    "fri": 4,
    "friday": 4,
    "sat": 5,
    "saturday": 5,
    "sun": 6,
    "sunday": 6,
}


@dataclass
class BookingExtraction:
    therapist_email: str | None
    requested_datetime: datetime | None
    sender_name: str | None = None
    clarification: str | None = None


def is_booking_intent(message: str) -> bool:
    lower = message.lower()
    has_booking_action = any(
        phrase in lower
        for phrase in [
            "email",
            "send",
            "appointment",
            "book",
            "booking",
            "request an appointment",
            "request appointment",
        ]
    )
    if not has_booking_action:
        return False

    has_email_address = EMAIL_RE.search(message) is not None
    has_datetime_hint = bool(
        ISO_DATETIME_RE.search(message)
        or DATE_TIME_RE.search(message)
        or DATE_ONLY_RE.search(message)
        or "tomorrow" in lower
        or WEEKDAY_RE.search(lower)
    )
    return has_email_address or has_datetime_hint


def is_affirmative(message: str) -> bool:
    normalized = re.sub(r"[^a-z]+", " ", message.lower()).strip().split()
    return any(token in {"yes", "send", "confirm"} for token in normalized)


def is_negative(message: str) -> bool:
    normalized = re.sub(r"[^a-z]+", " ", message.lower()).strip().split()
    return any(token in {"no", "cancel", "stop"} for token in normalized)


def extract_email(message: str) -> str | None:
    match = EMAIL_RE.search(message)
    if not match:
        return None
    return match.group(1).lower()


def extract_sender_name(message: str) -> str | None:
    match = NAME_RE.search(message)
    if not match:
        return None
    name = " ".join(match.group(1).strip().split())
    return name[:80] if name else None


def _parse_time_token(text: str) -> tuple[int, int] | None:
    match = TIME_RE.search(text)
    if not match:
        return None
    hour = int(match.group(1))
    minute = int(match.group(2) or 0)
    ampm = (match.group(3) or "").lower()
    if minute > 59:
        return None
    if ampm:
        if hour < 1 or hour > 12:
            return None
        if ampm == "pm" and hour != 12:
            hour += 12
        if ampm == "am" and hour == 12:
            hour = 0
    elif hour > 23:
        return None
    return hour, minute


def _build_datetime_from_date_time_tokens(
    *,
    date_text: str,
    hour: int,
    minute: int,
    tz: ZoneInfo,
) -> tuple[datetime | None, str | None]:
    try:
        base_date = datetime.strptime(date_text, "%Y-%m-%d").date()
    except ValueError:
        return None, "I could not parse the date. Please use YYYY-MM-DD."
    return datetime(
        year=base_date.year,
        month=base_date.month,
        day=base_date.day,
        hour=hour,
        minute=minute,
        tzinfo=tz,
    ), None


def _parse_requested_datetime_with_clarification(
    message: str,
    *,
    tz: ZoneInfo = STOCKHOLM_TZ,
    now: datetime | None = None,
) -> tuple[datetime | None, str | None]:
    now_local = now.astimezone(tz) if now else datetime.now(tz)

    iso_match = ISO_DATETIME_RE.search(message)
    if iso_match:
        raw = iso_match.group(1).replace(" ", "T")
        if raw.endswith("Z"):
            raw = raw[:-1] + "+00:00"
        try:
            dt = datetime.fromisoformat(raw)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=tz)
            else:
                dt = dt.astimezone(tz)
            return dt, None
        except ValueError:
            return None, "I could not parse the date/time. Please use format YYYY-MM-DD HH:MM."

    lower = message.lower()
    has_tomorrow = "tomorrow" in lower
    weekday_match = WEEKDAY_RE.search(lower)
    time_value = _parse_time_token(message)

    if has_tomorrow:
        if not time_value:
            return None, "Please include a time (for example: tomorrow 15:00)."
        target_date = (now_local + timedelta(days=1)).date()
        return datetime(
            target_date.year,
            target_date.month,
            target_date.day,
            time_value[0],
            time_value[1],
            tzinfo=tz
        ), None

    if weekday_match:
        if not time_value:
            return None, "Please include a time with the weekday (for example: Tue 15:00)."
        weekday_token = weekday_match.group(1).lower()
        weekday_target = WEEKDAY_MAP[weekday_token]
        delta_days = (weekday_target - now_local.weekday()) % 7
        candidate_date = (now_local + timedelta(days=delta_days)).date()
        candidate_dt = datetime(
            candidate_date.year,
            candidate_date.month,
            candidate_date.day,
            time_value[0],
            time_value[1],
            tzinfo=tz
        )
        if candidate_dt <= now_local:
            candidate_dt = candidate_dt + timedelta(days=7)
        return candidate_dt, None

    explicit_match = DATE_TIME_RE.search(message)
    if explicit_match:
        parsed_time = _parse_time_token(explicit_match.group(2))
        if not parsed_time:
            return None, "I could not parse the time. Please include HH:MM (24h) or 3pm."
        return _build_datetime_from_date_time_tokens(
            date_text=explicit_match.group(1),
            hour=parsed_time[0],
            minute=parsed_time[1],
            tz=tz,
        )

    date_time_at_match = DATE_TIME_WITH_AT_RE.search(message)
    if date_time_at_match:
        return _build_datetime_from_date_time_tokens(
            date_text=date_time_at_match.group(1),
            hour=int(date_time_at_match.group(2)),
            minute=int(date_time_at_match.group(3)),
            tz=tz,
        )

    time_on_date_match = TIME_ON_DATE_RE.search(message)
    if time_on_date_match:
        return _build_datetime_from_date_time_tokens(
            date_text=time_on_date_match.group(3),
            hour=int(time_on_date_match.group(1)),
            minute=int(time_on_date_match.group(2)),
            tz=tz,
        )

    on_date_at_time_match = ON_DATE_AT_TIME_RE.search(message)
    if on_date_at_time_match:
        return _build_datetime_from_date_time_tokens(
            date_text=on_date_at_time_match.group(1),
            hour=int(on_date_at_time_match.group(2)),
            minute=int(on_date_at_time_match.group(3)),
            tz=tz,
        )

    date_token_match = DATE_ONLY_RE.search(message)
    time_token_match = TIME_HHMM_RE.search(message)
    if date_token_match and time_token_match:
        return _build_datetime_from_date_time_tokens(
            date_text=date_token_match.group(1),
            hour=int(time_token_match.group(1)),
            minute=int(time_token_match.group(2)),
            tz=tz,
        )

    if date_token_match and not time_token_match:
        return None, "Please include a time with the date (for example: 2026-02-14 15:00)."
    if time_token_match and not date_token_match:
        return None, "Please include a date with the time (for example: 2026-02-14 15:00)."

    return None, None


def parse_requested_datetime(
    message: str,
    *,
    tz: ZoneInfo = STOCKHOLM_TZ,
    now: datetime | None = None,
) -> str | None:
    parsed_dt, _ = _parse_requested_datetime_with_clarification(message, tz=tz, now=now)
    if not parsed_dt:
        return None
    return parsed_dt.astimezone(tz).isoformat()


def extract_booking_data(message: str, now: datetime | None = None) -> BookingExtraction:
    therapist_email = extract_email(message)
    requested_dt, clarification = _parse_requested_datetime_with_clarification(message, now=now)
    return BookingExtraction(
        therapist_email=therapist_email,
        requested_datetime=requested_dt,
        sender_name=extract_sender_name(message),
        clarification=clarification
    )


def build_booking_email_content(
    user: User | None,
    therapist_email: str,
    requested_datetime: datetime,
    sender_name: str | None = None,
    sender_email: str | None = None,
) -> dict[str, str]:
    resolved_name = sender_name or (user.name if user and user.name else "A client")
    resolved_email = sender_email or (user.email if user and user.email else None)
    timestamp = requested_datetime.astimezone(STOCKHOLM_TZ).strftime("%Y-%m-%d %H:%M")
    subject = f"Appointment request - {timestamp} (Europe/Stockholm)"
    if resolved_email:
        signature = f"{resolved_name}\n{resolved_email}"
    else:
        signature = resolved_name
    body = (
        "Hello,\n\n"
        f"I would like to request an appointment on {timestamp} (Europe/Stockholm).\n\n"
        f"Best regards,\n{signature}"
    )
    return {
        "therapist_email": therapist_email,
        "requested_datetime_iso": requested_datetime.astimezone(STOCKHOLM_TZ).isoformat(),
        "subject": subject,
        "body": body,
        "reply_to": resolved_email
    }


def load_pending_booking(
    db: Session,
    user_id: str,
    now: datetime | None = None
) -> tuple[PendingAction | None, bool]:
    now_utc = now.astimezone(ZoneInfo("UTC")) if now else datetime.now(ZoneInfo("UTC"))
    pending = db.execute(
        select(PendingAction)
        .where(
            PendingAction.user_id == user_id,
            PendingAction.action_type == BOOKING_ACTION_TYPE
        )
        .order_by(desc(PendingAction.created_at))
    ).scalar_one_or_none()
    if not pending:
        return None, False
    expires_at = pending.expires_at
    expires_utc = expires_at.astimezone(ZoneInfo("UTC")) if expires_at.tzinfo else expires_at.replace(tzinfo=ZoneInfo("UTC"))
    if expires_utc <= now_utc:
        db.delete(pending)
        db.commit()
        return None, True
    return pending, False


def save_pending_booking(
    db: Session,
    user_id: str,
    payload: dict[str, Any],
    now: datetime | None = None
) -> PendingAction:
    now_utc = now.astimezone(ZoneInfo("UTC")) if now else datetime.now(ZoneInfo("UTC"))
    expires_at = now_utc + timedelta(minutes=BOOKING_TTL_MINUTES)
    existing = db.execute(
        select(PendingAction).where(
            PendingAction.user_id == user_id,
            PendingAction.action_type == BOOKING_ACTION_TYPE
        )
    ).scalars().all()
    for row in existing:
        db.delete(row)
    pending = PendingAction(
        user_id=user_id,
        action_type=BOOKING_ACTION_TYPE,
        payload_json=json.dumps(payload),
        expires_at=expires_at
    )
    db.add(pending)
    db.commit()
    db.refresh(pending)
    return pending


def clear_pending_booking(db: Session, pending: PendingAction) -> None:
    db.delete(pending)
    db.commit()


def parse_pending_payload(pending: PendingAction) -> dict[str, Any]:
    try:
        payload = json.loads(pending.payload_json)
    except (ValueError, TypeError):
        return {}
    if not isinstance(payload, dict):
        return {}
    return payload
