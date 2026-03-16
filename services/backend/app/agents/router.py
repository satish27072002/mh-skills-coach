from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable, Literal

from app.booking import is_booking_intent
from app.safety import classify_intent


THERAPIST_SEARCH_KEYWORDS = [
    # Existing
    "find therapist", "find a therapist", "therapist near", "therapists near",
    "clinic near", "provider near", "psychiatry", "psychiatrist",
    "psychiatry clinic", "bup", "mottagning", "mental health clinic", "find clinic",
    # Broader professional types
    "find a doctor", "doctor near", "find doctor",
    "find a counselor", "find a counsellor", "find counselor", "find counsellor",
    "counseling near", "counselling near",
    "find a psychologist", "find psychologist", "psychologist near",
    "psychotherapy", "psychotherapist",
    # Natural phrasing
    "therapy near", "therapy in", "therapist in",
    "counselor in", "counsellor in", "psychologist in",
    "see a therapist", "see a counselor", "see a psychologist", "see a doctor",
    "looking for a therapist", "looking for therapist",
    "need a therapist", "need therapist",
    "recommend a therapist", "suggest a therapist",
    "any therapists", "any counselors", "any psychologists",
    "mental health professional", "mental health provider",
    "therapy services", "counseling services", "counselling services",
    "where can i find a therapist", "where can i get help",
    "help me find a therapist", "help me find therapist",
    "i need professional help",
]


ChatRoute = Literal["THERAPIST_SEARCH", "BOOKING_EMAIL", "COACH"]
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
EMAIL_INTENT_KEYWORDS = (
    "send email", "send an email", "send a email",
    "write email", "write an email",
    "compose email", "compose an email",
    "draft email", "draft an email",
    "email",
    "appointment", "schedule", "book", "booking",
    "contact therapist", "contact them",
    "reach out to", "reach out",
    "send a message", "send message",
    "help me book", "help me schedule",
)


def _is_confirmation_only_message(message: str) -> bool:
    tokens = re.sub(r"[^a-z]+", " ", message.lower()).strip().split()
    if not tokens:
        return False
    allowed = {"yes", "confirm", "confirmed", "ok", "okay", "y", "no", "cancel", "n"}
    return all(token in allowed for token in tokens)


@dataclass(frozen=True)
class RouterInput:
    message: str
    has_pending_booking: bool
    has_pending_therapist_location: bool


def _looks_like_location_reply(message: str) -> bool:
    cleaned = message.strip()
    if not cleaned:
        return False
    if len(cleaned.split()) > 4:
        return False
    return bool(re.match(r"^[\w\-\s]{2,40}$", cleaned, flags=re.IGNORECASE))


def _is_therapist_search_intent(message: str) -> bool:
    lower = message.lower()
    if any(keyword in lower for keyword in THERAPIST_SEARCH_KEYWORDS):
        return True
    # keep existing fallback classifier behavior
    return classify_intent(message) == "therapist_search"


def _has_strong_email_intent(message: str) -> bool:
    lower = message.lower()
    if EMAIL_RE.search(message):
        return True
    return any(keyword in lower for keyword in EMAIL_INTENT_KEYWORDS)


class ChatRouter:
    def __init__(self, llm_fallback: Callable[[str], ChatRoute | None] | None = None):
        self._llm_fallback = llm_fallback

    def route(self, data: RouterInput) -> ChatRoute:
        message = data.message.strip()

        # Pending booking always continues through booking agent first.
        if data.has_pending_booking:
            return "BOOKING_EMAIL"

        if data.has_pending_therapist_location and _looks_like_location_reply(message):
            return "THERAPIST_SEARCH"

        if _has_strong_email_intent(message):
            return "BOOKING_EMAIL"

        if _is_therapist_search_intent(message):
            return "THERAPIST_SEARCH"

        if is_booking_intent(message):
            return "BOOKING_EMAIL"

        if _is_confirmation_only_message(message):
            return "BOOKING_EMAIL"

        if self._llm_fallback:
            candidate = self._llm_fallback(message)
            if candidate in {"THERAPIST_SEARCH", "BOOKING_EMAIL", "COACH"}:
                return candidate

        return "COACH"
