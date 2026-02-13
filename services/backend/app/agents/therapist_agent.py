from __future__ import annotations

import re
from dataclasses import dataclass, replace
from typing import Callable

from fastapi import HTTPException, Request

from app.models import User
from app.schemas import ChatResponse, PremiumCta, TherapistResult


LAST_THERAPIST_LOCATION_BY_SESSION: dict[str, str] = {}
PENDING_THERAPIST_QUERY_BY_SESSION: dict[str, "TherapistSearchParams"] = {}

CITY_TOKEN_RE = re.compile(r"^[\w\-\s]{2,40}$", flags=re.IGNORECASE)


def extract_location(message: str) -> str | None:
    match = re.search(r"\b(?:near|in|around|at)\s+(.+)", message, flags=re.IGNORECASE)
    if match:
        tail = re.split(
            r"\bwithin\s+\d+\s*(?:km|kilometers?|kilometres?)?\b|\bfor\b|[,.!?]",
            match.group(1),
            maxsplit=1,
            flags=re.IGNORECASE,
        )[0]
        location = tail.strip(" .?")
        if location.lower() in {"me", "here", "my area"}:
            return None
        return location or None
    return None


def extract_location_from_short_reply(message: str) -> str | None:
    tail = re.split(
        r"\bwithin\s+\d+\s*(?:km|kilometers?|kilometres?)?\b|\bfor\b|[,.!?]",
        message,
        maxsplit=1,
        flags=re.IGNORECASE,
    )[0]
    location = tail.strip(" .?")
    if not location:
        return None
    if location.lower() in {"me", "here", "my area"}:
        return None
    return location


def extract_radius_km(message: str) -> int | None:
    match = re.search(
        r"\bwithin\s+(\d{1,3})(?:\s*(?:km|kilometers?|kilometres?))?\b",
        message,
        flags=re.IGNORECASE,
    )
    if not match:
        match = re.search(
            r"\b(\d{1,3})\s*(?:km|kilometers?|kilometres?)\b",
            message,
            flags=re.IGNORECASE,
        )
    if not match:
        return None
    return min(max(int(match.group(1)), 1), 50)


def extract_specialty(message: str) -> str | None:
    match = re.search(r"\bfor\s+(.+)", message, flags=re.IGNORECASE)
    if not match:
        return None
    candidate = re.split(
        r"\bwithin\s+\d+\s*(?:km|kilometers?|kilometres?)?\b|\b(?:near|in|around|at)\b|[,.!?]",
        match.group(1),
        maxsplit=1,
        flags=re.IGNORECASE,
    )[0].strip(" .?")
    if not candidate or candidate.lower() in {"me", "here", "my area"}:
        return None
    return candidate


def extract_limit(message: str) -> int:
    match = re.search(
        r"\b(\d{1,2})\s*(?:therapists?|clinics?|providers?)\b",
        message,
        flags=re.IGNORECASE,
    )
    if not match:
        return 10
    return min(max(int(match.group(1)), 1), 10)


def normalize_specialty(specialty: str | None) -> str | None:
    if specialty is None:
        return None
    normalized = specialty.strip()
    return normalized or None


def _session_location_key(user: User | None, request: Request, session_cookie_name: str) -> str | None:
    if user:
        return f"user:{user.id}"
    session_cookie = request.cookies.get(session_cookie_name)
    if session_cookie:
        return f"session:{session_cookie}"
    user_agent = (request.headers.get("user-agent") or "").strip()[:40]
    client_host = request.client.host if request.client else "unknown"
    return f"anon:{client_host}:{user_agent}"


def remember_location(
    *,
    user: User | None,
    request: Request,
    location: str | None,
    session_cookie_name: str,
) -> None:
    if not location:
        return
    normalized = location.strip()
    if not normalized:
        return
    key = _session_location_key(user, request, session_cookie_name)
    if not key:
        return
    LAST_THERAPIST_LOCATION_BY_SESSION[key] = normalized


def clear_remembered_location(
    *,
    user: User | None,
    request: Request,
    session_cookie_name: str,
) -> None:
    key = _session_location_key(user, request, session_cookie_name)
    if not key:
        return
    LAST_THERAPIST_LOCATION_BY_SESSION.pop(key, None)


def get_remembered_location(
    *,
    user: User | None,
    request: Request,
    session_cookie_name: str,
) -> str | None:
    key = _session_location_key(user, request, session_cookie_name)
    if not key:
        return None
    return LAST_THERAPIST_LOCATION_BY_SESSION.get(key)


@dataclass(frozen=True)
class TherapistSearchParams:
    location_text: str | None
    radius_km: int
    specialty: str | None
    limit: int


class TherapistSearchAgent:
    def __init__(
        self,
        *,
        search_fn: Callable[[str, int | None, str | None, int], list[TherapistResult]],
        dev_mode: bool,
        session_cookie_name: str,
    ):
        self._search_fn = search_fn
        self._dev_mode = dev_mode
        self._session_cookie_name = session_cookie_name

    @property
    def dev_mode(self) -> bool:
        return self._dev_mode

    def parse_message(self, message: str) -> TherapistSearchParams:
        radius_km = extract_radius_km(message) or 25
        return TherapistSearchParams(
            location_text=extract_location(message),
            radius_km=min(max(radius_km, 1), 50),
            specialty=normalize_specialty(extract_specialty(message)),
            limit=extract_limit(message),
        )

    def remember_location(self, *, user: User | None, request: Request, location: str | None) -> None:
        remember_location(
            user=user,
            request=request,
            location=location,
            session_cookie_name=self._session_cookie_name,
        )

    def get_remembered_location(self, *, user: User | None, request: Request) -> str | None:
        return get_remembered_location(
            user=user,
            request=request,
            session_cookie_name=self._session_cookie_name,
        )

    def clear_remembered_location(self, *, user: User | None, request: Request) -> None:
        clear_remembered_location(
            user=user,
            request=request,
            session_cookie_name=self._session_cookie_name,
        )

    def has_pending_location_request(self, *, user: User | None, request: Request) -> bool:
        key = _session_location_key(user, request, self._session_cookie_name)
        if not key:
            return False
        return key in PENDING_THERAPIST_QUERY_BY_SESSION

    def _get_pending_query(self, *, user: User | None, request: Request) -> TherapistSearchParams | None:
        key = _session_location_key(user, request, self._session_cookie_name)
        if not key:
            return None
        return PENDING_THERAPIST_QUERY_BY_SESSION.get(key)

    def _set_pending_query(
        self,
        *,
        user: User | None,
        request: Request,
        query: TherapistSearchParams,
    ) -> None:
        key = _session_location_key(user, request, self._session_cookie_name)
        if not key:
            return
        PENDING_THERAPIST_QUERY_BY_SESSION[key] = query

    def _clear_pending_query(self, *, user: User | None, request: Request) -> None:
        key = _session_location_key(user, request, self._session_cookie_name)
        if not key:
            return
        PENDING_THERAPIST_QUERY_BY_SESSION.pop(key, None)

    @staticmethod
    def _looks_like_location_reply(message: str) -> bool:
        cleaned = message.strip()
        if not cleaned:
            return False
        if len(cleaned.split()) > 4:
            return False
        return bool(CITY_TOKEN_RE.match(cleaned))

    def search_with_retries(
        self,
        *,
        location_text: str,
        radius_km: int | None,
        specialty: str | None,
        limit: int | None = None,
    ) -> tuple[list[TherapistResult], str | None]:
        requested_radius = min(max(radius_km or 25, 1), 50)
        normalized_specialty = normalize_specialty(specialty)
        requested_limit = min(max(limit or 10, 1), 10)
        attempts: list[tuple[int | None, str | None, str | None]] = [
            (requested_radius, normalized_specialty, None),
        ]
        if normalized_specialty:
            attempts.append((requested_radius, None, "specialty"))
        if requested_radius < 25:
            attempts.append((25, None, "radius"))

        seen: set[tuple[int | None, str | None]] = set()
        for attempt_radius, attempt_specialty, reason in attempts:
            dedupe_key = (attempt_radius, attempt_specialty)
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)
            results = self._search_fn(
                location_text,
                attempt_radius,
                attempt_specialty,
                requested_limit,
            )
            if results:
                return results, reason
        return [], None

    def handle(self, *, user: User | None, request: Request, message: str) -> ChatResponse:
        if not user and not self._dev_mode:
            return ChatResponse(
                coach_message="Please sign in to use therapist search.",
                premium_cta=PremiumCta(
                    enabled=True,
                    message="Sign in and upgrade to premium to unlock therapist search.",
                ),
            )

        if user and not user.is_premium and not self._dev_mode:
            return ChatResponse(
                coach_message="Therapist search is available with premium access.",
                premium_cta=PremiumCta(
                    enabled=True,
                    message="Unlock therapist search to see local providers.",
                ),
            )

        parsed = self.parse_message(message)
        pending_query = self._get_pending_query(user=user, request=request)
        location = parsed.location_text
        if not location and pending_query and self._looks_like_location_reply(message):
            location = extract_location_from_short_reply(message)
            parsed = replace(
                pending_query,
                location_text=location,
                radius_km=extract_radius_km(message) or pending_query.radius_km,
                specialty=normalize_specialty(extract_specialty(message)) or pending_query.specialty,
                limit=extract_limit(message) if re.search(r"\d", message) else pending_query.limit,
            )
        if not location:
            # Avoid leaking previous search context into a new therapist-search request.
            self.clear_remembered_location(user=user, request=request)
            self._clear_pending_query(user=user, request=request)
            self._set_pending_query(user=user, request=request, query=parsed)
            return ChatResponse(
                coach_message="Please share a city or postcode so I can search nearby providers.",
                therapists=[],
            )
        self._clear_pending_query(user=user, request=request)

        try:
            results, fallback_reason = self.search_with_retries(
                location_text=location,
                radius_km=parsed.radius_km,
                specialty=parsed.specialty,
                limit=parsed.limit,
            )
        except HTTPException:
            results, fallback_reason = [], None

        if not results:
            return ChatResponse(
                coach_message=(
                    f"No providers found near {location} within {parsed.radius_km} km. "
                    "Try a larger radius or nearby area."
                ),
                therapists=[],
            )

        self.remember_location(user=user, request=request, location=location)
        if fallback_reason == "specialty":
            return ChatResponse(
                coach_message="No exact specialty match; showing nearby providers.",
                therapists=results,
            )
        if fallback_reason == "radius":
            return ChatResponse(
                coach_message="No providers found in the requested radius; showing nearby providers.",
                therapists=results,
            )

        return ChatResponse(
            coach_message=f"Here are therapist options near {location}.",
            therapists=results,
        )
