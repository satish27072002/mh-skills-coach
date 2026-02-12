from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
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
DATE_ONLY_RE = re.compile(r"\b(\d{4}-\d{2}-\d{2})\b")
DATE_TIME_RE = re.compile(r"\b(\d{4}-\d{2}-\d{2})\s+(\d{1,2}:\d{2}(?:\s*[ap]m)?)\b", re.IGNORECASE)
TIME_RE = re.compile(r"\b(\d{1,2})(?::(\d{2}))?\s*([ap]m)?\b", re.IGNORECASE)
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
    clarification: str | None = None


def is_booking_intent(message: str) -> bool:
    lower = message.lower()
    has_email_verb = "email" in lower or "send" in lower
    has_context = any(token in lower for token in ["appointment", "book", "booking", "therapist", "session"])
    has_email_address = EMAIL_RE.search(message) is not None
    return (has_email_verb and has_context) or (has_email_address and "appointment" in lower)


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


def parse_requested_datetime(message: str, now: datetime | None = None) -> tuple[datetime | None, str | None]:
    now_local = now.astimezone(STOCKHOLM_TZ) if now else datetime.now(STOCKHOLM_TZ)

    iso_match = ISO_DATETIME_RE.search(message)
    if iso_match:
        raw = iso_match.group(1).replace(" ", "T")
        if raw.endswith("Z"):
            raw = raw[:-1] + "+00:00"
        try:
            dt = datetime.fromisoformat(raw)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=STOCKHOLM_TZ)
            else:
                dt = dt.astimezone(STOCKHOLM_TZ)
            return dt, None
        except ValueError:
            return None, "I could not parse the date/time. Please use format YYYY-MM-DD HH:MM."

    explicit_match = DATE_TIME_RE.search(message)
    if explicit_match:
        try:
            base_date = datetime.strptime(explicit_match.group(1), "%Y-%m-%d").date()
        except ValueError:
            return None, "I could not parse the date. Please use YYYY-MM-DD."
        parsed_time = _parse_time_token(explicit_match.group(2))
        if not parsed_time:
            return None, "I could not parse the time. Please include HH:MM (24h) or 3pm."
        hour, minute = parsed_time
        return datetime(
            year=base_date.year,
            month=base_date.month,
            day=base_date.day,
            hour=hour,
            minute=minute,
            tzinfo=STOCKHOLM_TZ
        ), None

    lower = message.lower()
    has_tomorrow = "tomorrow" in lower
    weekday_match = WEEKDAY_RE.search(lower)
    has_date_only = DATE_ONLY_RE.search(message) is not None
    time_value = _parse_time_token(lower)

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
            tzinfo=STOCKHOLM_TZ
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
            tzinfo=STOCKHOLM_TZ
        )
        if candidate_dt <= now_local:
            candidate_dt = candidate_dt + timedelta(days=7)
        return candidate_dt, None

    if has_date_only and not time_value:
        return None, "Please include a time with the date (for example: 2026-02-14 15:00)."
    if time_value and not (has_tomorrow or weekday_match or has_date_only):
        return None, "Please include a date with the time (for example: 2026-02-14 15:00)."

    return None, None


def extract_booking_data(message: str, now: datetime | None = None) -> BookingExtraction:
    therapist_email = extract_email(message)
    requested_dt, clarification = parse_requested_datetime(message, now=now)
    return BookingExtraction(
        therapist_email=therapist_email,
        requested_datetime=requested_dt,
        clarification=clarification
    )


def build_booking_email_content(
    user: User,
    therapist_email: str,
    requested_datetime: datetime
) -> dict[str, str]:
    timestamp = requested_datetime.astimezone(STOCKHOLM_TZ).strftime("%Y-%m-%d %H:%M")
    subject = f"Appointment request - {timestamp} (Europe/Stockholm)"
    body = (
        "Hello,\n\n"
        f"I would like to request an appointment on {timestamp} (Europe/Stockholm).\n\n"
        f"Best regards,\n{user.name}\n{user.email}"
    )
    return {
        "therapist_email": therapist_email,
        "requested_datetime_iso": requested_datetime.astimezone(STOCKHOLM_TZ).isoformat(),
        "subject": subject,
        "body": body,
        "reply_to": user.email
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
    payload: dict[str, str | None],
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


def parse_pending_payload(pending: PendingAction) -> dict[str, str | None]:
    try:
        payload = json.loads(pending.payload_json)
    except (ValueError, TypeError):
        return {}
    if not isinstance(payload, dict):
        return {}
    return payload
