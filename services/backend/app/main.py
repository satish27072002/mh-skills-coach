import base64
import hashlib
import json
import logging
import re
import secrets
import urllib.parse
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any, AsyncIterator
from uuid import UUID
from zoneinfo import ZoneInfo

# Monitoring & security — must be imported before first use
from .monitoring.logger import configure_logging, get_logger, log_event, new_correlation_id, set_correlation_id, Timer
from .security.rate_limiter import RateLimiter, RateLimitExceeded

import httpx
import stripe
from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse
from google.auth.transport.requests import Request as GoogleRequest
from google.oauth2 import id_token as google_id_token
from sqlalchemy import select
from sqlalchemy.orm import Session

from .agents import BookingEmailAgent, ChatRouter, RouterInput, SafetyGate, TherapistSearchAgent
from .agents.therapist_agent import LAST_THERAPIST_LOCATION_BY_SESSION
from .config import settings
from .agent_graph import run_agent
from .booking import (
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
from .db import ensure_embedding_dimension_compatible, get_db, init_db, pgvector_ready
from .embed_dimension import get_active_embedding_dim, get_cached_embedding_dim
from .email_orchestrator import EmailSendPayload, send_email_for_user
from .llm.provider import (
    ConfigurationError,
    probe_ollama_connectivity,
    probe_openai_connectivity,
    validate_provider_configuration,
)
from .mcp_client import mcp_therapist_search, probe_mcp_health
from .models import StripeEvent, User
from .safety import (
    classify_intent,
    contains_jailbreak_attempt,
    is_prescription_request,
    scope_check,
    route_message,
    is_crisis,
)
from .schemas import (
    BookingProposal,
    ChatRequest,
    ChatResponse,
    CheckoutSessionResponse,
    PremiumCta,
    TherapistSearchRequest,
    TherapistSearchResponse
)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    import os
    # Configure LangSmith tracing if API key is present
    if settings.langsmith_api_key:
        os.environ["LANGSMITH_API_KEY"] = settings.langsmith_api_key
        os.environ["LANGCHAIN_TRACING_V2"] = settings.langchain_tracing_v2
        os.environ["LANGCHAIN_PROJECT"] = settings.langchain_project
        logger.info("LangSmith tracing enabled for project: %s", settings.langchain_project)
    else:
        logger.info("LangSmith tracing disabled (no LANGSMITH_API_KEY)")

    try:
        validate_provider_configuration()
        get_active_embedding_dim()
    except ConfigurationError as exc:
        logger.critical("Invalid provider configuration: %s", exc)
        raise
    except RuntimeError as exc:
        logger.critical("Invalid embedding configuration: %s", exc)
        raise
    init_db()
    ensure_embedding_dimension_compatible()
    yield


app = FastAPI(title="mh-skills-backend", lifespan=lifespan)

def _build_cors_origins(frontend_url: str) -> list[str]:
    candidates = ["http://localhost:3000"]
    if frontend_url:
        candidates.append(frontend_url.rstrip("/"))
    origins: list[str] = []
    seen: set[str] = set()
    for origin in candidates:
        if origin and origin not in seen:
            origins.append(origin)
            seen.add(origin)
    return origins


app.add_middleware(
    CORSMiddleware,
    allow_origins=_build_cors_origins(settings.frontend_url),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"]
)

GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_ISSUERS = {"accounts.google.com", "https://accounts.google.com"}
BOOKING_SESSION_COOKIE_NAME = "mh_booking_session"

# Configure structured logging at module load time
configure_logging(level=settings.log_level, fmt=settings.log_format)
logger = get_logger(__name__)

UTC = ZoneInfo("UTC")
_LAST_THERAPIST_LOCATION_BY_SESSION = LAST_THERAPIST_LOCATION_BY_SESSION

# ---------------------------------------------------------------------------
# Rate limiter — shared across requests (in-process, thread-safe)
# ---------------------------------------------------------------------------
_rate_limiter = RateLimiter(
    max_requests=settings.rate_limit_chat_requests,
    window_seconds=settings.rate_limit_window_seconds,
)

# ---------------------------------------------------------------------------
# Conversation history store — keyed by session ID
# Stores list of {"role": "user"/"assistant", "content": "..."} dicts
# Capped at settings.conversation_history_max_turns * 2 messages
# ---------------------------------------------------------------------------
_conversation_store: dict[str, list[dict[str, str]]] = {}


def _get_session_key(user: Any, request: Any) -> str:
    """Build a stable session key from user ID or session cookie."""
    if user and hasattr(user, "id"):
        return f"user:{user.id}"
    session_cookie = request.cookies.get(settings.session_cookie_name)
    if session_cookie:
        return f"session:{session_cookie}"
    # Fallback to client IP
    client_host = getattr(request.client, "host", "unknown") if request.client else "unknown"
    return f"ip:{client_host}"


def _load_history(session_key: str) -> list[dict[str, str]]:
    """Load conversation history for a session."""
    return list(_conversation_store.get(session_key, []))


def _save_history(session_key: str, history: list[dict[str, str]]) -> None:
    """Save conversation history, capping at max turns."""
    max_messages = settings.conversation_history_max_turns * 2  # user + assistant per turn
    if len(history) > max_messages:
        history = history[-max_messages:]
    _conversation_store[session_key] = history


def _append_to_history(
    session_key: str,
    user_message: str,
    assistant_message: str,
) -> None:
    """Append a user+assistant exchange to conversation history."""
    history = _load_history(session_key)
    history.append({"role": "user", "content": user_message})
    history.append({"role": "assistant", "content": assistant_message})
    _save_history(session_key, history)


def _extract_location(message: str) -> str | None:
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


def _extract_radius_km(message: str) -> int | None:
    match = re.search(
        r"\bwithin\s+(\d{1,3})(?:\s*(?:km|kilometers?|kilometres?))?\b",
        message,
        flags=re.IGNORECASE
    )
    if not match:
        match = re.search(
            r"\b(\d{1,3})\s*(?:km|kilometers?|kilometres?)\b",
            message,
            flags=re.IGNORECASE
        )
    if not match:
        return None
    return min(max(int(match.group(1)), 1), 50)


def _extract_specialty(message: str) -> str | None:
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


def _normalize_specialty(specialty: str | None) -> str | None:
    if specialty is None:
        return None
    normalized = specialty.strip()
    return normalized or None


def _session_location_key(user: User | None, request: Request) -> str | None:
    if user:
        return f"user:{user.id}"
    session_cookie = request.cookies.get(settings.session_cookie_name)
    if session_cookie:
        return f"session:{session_cookie}"
    return None


def _remember_therapist_location(user: User | None, request: Request, location: str | None) -> None:
    if not location:
        return
    normalized = location.strip()
    if not normalized:
        return
    key = _session_location_key(user, request)
    if not key:
        return
    _LAST_THERAPIST_LOCATION_BY_SESSION[key] = normalized


def _get_remembered_therapist_location(user: User | None, request: Request) -> str | None:
    key = _session_location_key(user, request)
    if not key:
        return None
    return _LAST_THERAPIST_LOCATION_BY_SESSION.get(key)


def _run_therapist_search(
    location: str,
    radius_km: int | None = None,
    specialty: str | None = None,
    limit: int = 10,
) -> list:
    return mcp_therapist_search(
        location_text=location,
        radius_km=radius_km,
        specialty=_normalize_specialty(specialty),
        limit=min(max(limit, 1), 10),
    )


def _therapist_search_with_retries(
    *,
    location: str,
    radius_km: int | None,
    specialty: str | None
) -> tuple[list, str | None]:
    requested_radius = min(max(radius_km, 1), 50) if radius_km is not None else None
    normalized_specialty = _normalize_specialty(specialty)
    attempts: list[tuple[int | None, str | None, str | None]] = [
        (requested_radius, normalized_specialty, None),
    ]
    if normalized_specialty:
        attempts.append((requested_radius, None, "specialty"))
    if requested_radius is None or requested_radius < 25:
        attempts.append((25, None, "radius"))

    deduped_attempts: list[tuple[int | None, str | None, str | None]] = []
    seen: set[tuple[int | None, str | None]] = set()
    for radius, attempt_specialty, reason in attempts:
        dedupe_key = (radius, attempt_specialty)
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        deduped_attempts.append((radius, attempt_specialty, reason))

    for radius, attempt_specialty, reason in deduped_attempts:
        results = _run_therapist_search(
            location=location,
            radius_km=radius,
            specialty=attempt_specialty
        )
        if results:
            return results, reason

    return [], None


def _chat_therapist_search_response(user: User | None, request: Request, message: str) -> ChatResponse:
    if not user:
        return ChatResponse(
            coach_message="Please sign in to use therapist search.",
            premium_cta=PremiumCta(
                enabled=True,
                message="Sign in and upgrade to premium to unlock therapist search."
            )
        )
    if not user.is_premium and not settings.dev_mode:
        return ChatResponse(
            coach_message="Therapist search is available with premium access.",
            premium_cta=PremiumCta(
                enabled=True,
                message="Unlock therapist search to see local providers."
            )
        )
    location = _extract_location(message) or "your area"
    radius_km = _extract_radius_km(message)
    specialty = _extract_specialty(message)
    fallback_reason: str | None = None

    try:
        results, fallback_reason = _therapist_search_with_retries(
            location=location,
            radius_km=radius_km,
            specialty=specialty
        )
    except HTTPException:
        results = []

    if not results:
        return ChatResponse(
            coach_message=f"No providers found near {location}. Try a nearby city or postcode.",
            therapists=[]
        )
    _remember_therapist_location(user=user, request=request, location=location)
    if fallback_reason:
        if fallback_reason == "specialty":
            coach_message = "No exact specialty match; showing nearby providers."
        else:
            coach_message = "No providers found in the requested radius; showing nearby providers."
        return ChatResponse(
            coach_message=coach_message,
            therapists=results
        )
    return ChatResponse(
        coach_message=f"Here are therapist options near {location}.",
        therapists=results
    )


def _chat_crisis_response(user: User | None, request: Request, message: str) -> ChatResponse:
    location = _extract_location(message) or _get_remembered_therapist_location(user, request) or "Stockholm"
    requested_radius = _extract_radius_km(message) or 25
    radius_km = min(max(requested_radius, 1), 50)
    specialty = _extract_specialty(message)

    therapists: list = []
    try:
        therapists, _ = _therapist_search_with_retries(
            location=location,
            radius_km=radius_km,
            specialty=specialty
        )
    except HTTPException:
        therapists = []

    if therapists:
        _remember_therapist_location(user=user, request=request, location=location)

    return ChatResponse(
        coach_message=(
            "I am really glad you reached out. Please seek immediate support right now. "
            "If you might act on these thoughts or are in immediate danger, call 112 immediately. "
            "You can also contact Mind Självmordslinjen at 90101 (chat/phone) for urgent emotional support, "
            "and use 1177 Vårdguiden for healthcare guidance and where to get care."
        ),
        resources=[
            {
                "title": "Emergency services (Sweden) - 112",
                "url": "https://www.112.se/"
            },
            {
                "title": "Mind Självmordslinjen - 90101",
                "url": "https://mind.se/hitta-hjalp/sjalvmordslinjen/"
            },
            {
                "title": "1177 Vårdguiden",
                "url": "https://www.1177.se/"
            }
        ],
        therapists=therapists,
        risk_level="crisis",
        premium_cta=None
    )


def _pending_payload_complete(payload: dict[str, str | None]) -> bool:
    return bool(
        payload.get("therapist_email")
        and payload.get("requested_datetime_iso")
        and payload.get("subject")
        and payload.get("body")
    )


def _requested_time_display(requested_datetime_iso: str) -> str:
    parsed = datetime.fromisoformat(requested_datetime_iso)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=STOCKHOLM_TZ)
    else:
        parsed = parsed.astimezone(STOCKHOLM_TZ)
    return f"{parsed.strftime('%Y-%m-%d %H:%M')} Europe/Stockholm"


def _booking_proposal_from_payload(
    payload: dict[str, str | None],
    expires_at: datetime
) -> BookingProposal:
    requested_datetime_iso = payload.get("requested_datetime_iso") or ""
    expires_display_dt = expires_at.astimezone(STOCKHOLM_TZ) if expires_at.tzinfo else expires_at.replace(tzinfo=UTC).astimezone(STOCKHOLM_TZ)
    return BookingProposal(
        therapist_email=payload.get("therapist_email") or "",
        requested_time=_requested_time_display(requested_datetime_iso),
        subject=payload.get("subject") or "",
        body=payload.get("body") or "",
        expires_at=expires_display_dt.isoformat()
    )


def _missing_booking_fields_message(payload: dict[str, str | None], clarification: str | None = None) -> str:
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


def _is_confirmation_only_message(message: str) -> bool:
    tokens = re.sub(r"[^a-z]+", " ", message.lower()).strip().split()
    if not tokens:
        return False
    allowed = {"yes", "confirm", "confirmed", "ok", "okay", "y"}
    return all(token in allowed for token in tokens)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}

@app.get("/status")
def status() -> dict[str, Any]:
    llm_provider = settings.llm_provider
    embed_provider = settings.embed_provider
    pg_ready = pgvector_ready()
    openai_enabled = llm_provider == "openai" or embed_provider == "openai"
    ollama_enabled = llm_provider == "ollama" or embed_provider == "ollama"
    openai_probe = probe_openai_connectivity() if openai_enabled else {"ok": False, "reason": "not_enabled"}
    openai_ok: bool = openai_probe["ok"]
    openai_reason: str = openai_probe["reason"]
    ollama_ok = probe_ollama_connectivity() if ollama_enabled else False
    mcp_ok = probe_mcp_health() if settings.mcp_base_url else False
    if llm_provider == "mock":
        llm_ok = True
    else:
        llm_ok = openai_ok if llm_provider == "openai" else ollama_ok
    agent_mode = "llm_rag" if llm_ok and pg_ready else "deterministic"
    if not pg_ready:
        reason = "pgvector not ready"
    elif not llm_ok:
        reason = f"{llm_provider} not reachable"
    else:
        reason = "LLM+RAG ready"
    model: str | None = None
    if llm_ok:
        if llm_provider == "openai":
            model = settings.openai_chat_model
        elif llm_provider == "ollama":
            model = settings.ollama_model
        else:
            model = "mock"
    provider_warnings: list[str] = []
    if openai_enabled and not settings.openai_api_key:
        if llm_provider == "openai":
            provider_warnings.append("LLM provider openai missing OPENAI_API_KEY.")
        if embed_provider == "openai":
            provider_warnings.append("Embedding provider openai missing OPENAI_API_KEY.")
    return {
        "agent_mode": agent_mode,
        "llm_provider": llm_provider,
        "embed_provider": embed_provider,
        "embed_dim": get_cached_embedding_dim(),
        "openai_ok": openai_ok,
        "openai_reason": openai_reason,
        "ollama_ok": ollama_ok,
        "mcp_ok": mcp_ok,
        "ollama_reachable": ollama_ok,
        "pgvector_ready": pg_ready,
        "model": model,
        "reason": reason,
        "provider_warnings": provider_warnings
    }


def _set_cookie(response: Response, name: str, value: str, request: Request | None = None) -> None:
    samesite = settings.cookie_samesite.lower()
    secure = settings.cookie_secure
    # Dev over plain HTTP cannot round-trip Secure cookies. Keep prod secure by default.
    if request is not None and settings.dev_mode:
        forwarded_proto = (request.headers.get("x-forwarded-proto") or "").split(",")[0].strip().lower()
        request_is_https = request.url.scheme == "https" or forwarded_proto == "https"
        if not request_is_https:
            secure = False
    if samesite == "none" and not secure:
        logger.warning("COOKIE_SAMESITE=None requires COOKIE_SECURE=true; forcing secure")
        secure = True
    response.set_cookie(
        name,
        value,
        httponly=True,
        secure=secure,
        samesite=samesite
    )


def _get_user_from_cookie(db: Session, request: Request) -> User | None:
    user_id = request.cookies.get(settings.session_cookie_name)
    if not user_id:
        return None
    try:
        parsed_user_id = UUID(user_id)
    except ValueError:
        return None
    return db.get(User, parsed_user_id)


def _get_booking_actor_key(user: User | None, request: Request) -> str | None:
    if user:
        return str(user.id)
    session_token = request.cookies.get(BOOKING_SESSION_COOKIE_NAME)
    if not session_token:
        return None
    normalized = session_token.strip()
    if not normalized:
        return None
    return f"anon:{normalized}"


def _ensure_booking_actor_key(user: User | None, request: Request, response: Response) -> str:
    existing = _get_booking_actor_key(user, request)
    if existing:
        return existing
    token = secrets.token_urlsafe(24)
    _set_cookie(response, BOOKING_SESSION_COOKIE_NAME, token, request=request)
    return f"anon:{token}"


def _parse_user_id(value: str | None) -> UUID | None:
    if not value:
        return None
    try:
        return UUID(value)
    except ValueError:
        return None


def _build_router() -> ChatRouter:
    return ChatRouter()


def _build_therapist_agent() -> TherapistSearchAgent:
    return TherapistSearchAgent(
        search_fn=_run_therapist_search,
        dev_mode=settings.dev_mode,
        session_cookie_name=settings.session_cookie_name,
    )


def _build_booking_agent() -> BookingEmailAgent:
    return BookingEmailAgent(send_email_fn=send_email_for_user)


def _code_challenge(code_verifier: str) -> str:
    digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")


def _exchange_code_for_tokens(code: str, code_verifier: str) -> tuple[dict[str, Any], int]:
    data = {
        "code": code,
        "client_id": settings.google_client_id,
        "client_secret": settings.google_client_secret,
        "redirect_uri": settings.google_redirect_uri,
        "grant_type": "authorization_code",
        "code_verifier": code_verifier
    }
    try:
        response = httpx.post(GOOGLE_TOKEN_URL, data=data, timeout=10.0)
        response.raise_for_status()
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail="google token exchange failed") from exc

    return response.json(), response.status_code


def _decode_jwt_claims(token: str) -> dict[str, Any]:
    claims = {"iss": None, "aud": None, "exp": None, "iat": None}
    parts = token.split(".")
    if len(parts) < 2:
        return claims
    payload_b64 = parts[1]
    padding = "=" * (-len(payload_b64) % 4)
    try:
        payload_bytes = base64.urlsafe_b64decode(payload_b64 + padding)
        payload = json.loads(payload_bytes.decode("utf-8"))
    except (ValueError, json.JSONDecodeError) as exc:
        logger.debug("JWT payload decode failed: %s", exc)
        return claims
    if isinstance(payload, dict):
        for key in claims:
            if key in payload:
                claims[key] = payload.get(key)
    return claims


def _verify_id_token(id_token: str, token_keys: list[str]) -> dict[str, Any]:
    try:
        claims = google_id_token.verify_oauth2_token(
            id_token,
            GoogleRequest(),
            settings.google_client_id,
            clock_skew_in_seconds=10,
        )
    except ValueError as exc:
        safe_claims = _decode_jwt_claims(id_token)
        logger.warning(
            "Google id_token verification failed: %s (decoded_claims=%s, token_keys=%s)",
            exc,
            safe_claims,
            token_keys
        )
        raise HTTPException(status_code=400, detail="invalid id_token") from exc

    if claims.get("iss") not in GOOGLE_ISSUERS:
        logger.warning("Google id_token invalid issuer: %s", claims.get("iss"))
        raise HTTPException(status_code=400, detail="invalid token issuer")
    logger.info("Google id_token claims: iss=%s aud=%s", claims.get("iss"), claims.get("aud"))
    return claims


@app.get("/auth/google/start")
def auth_google_start(request: Request) -> Response:
    if not settings.google_client_id:
        return JSONResponse(status_code=501, content={"error": "google oauth not configured"})

    code_verifier = secrets.token_urlsafe(48)
    state = secrets.token_urlsafe(16)
    challenge = _code_challenge(code_verifier)
    auth_url = (
        "https://accounts.google.com/o/oauth2/v2/auth"
        f"?client_id={settings.google_client_id}"
        f"&redirect_uri={settings.google_redirect_uri}"
        "&response_type=code"
        "&scope=openid%20email%20profile"
        f"&state={state}"
        "&code_challenge_method=S256"
        f"&code_challenge={challenge}"
    )

    response = RedirectResponse(url=auth_url, status_code=302)
    _set_cookie(response, "pkce_verifier", code_verifier, request=request)
    _set_cookie(response, "oauth_state", state, request=request)
    return response


@app.get("/auth/google/callback")
def auth_google_callback(request: Request, db: Session = Depends(get_db)) -> Response:
    code = request.query_params.get("code")
    state = request.query_params.get("state")
    error = request.query_params.get("error")
    stored_state = request.cookies.get("oauth_state")
    code_verifier = request.cookies.get("pkce_verifier")

    if error:
        redirect_url = settings.frontend_url or "http://localhost:3000"
        safe_error = urllib.parse.quote(error, safe="")
        return RedirectResponse(
            url=f"{redirect_url.rstrip('/')}/?auth_error={safe_error}",
            status_code=302
        )

    if not code or not state or state != stored_state:
        raise HTTPException(status_code=400, detail="invalid oauth state")
    if not code_verifier:
        raise HTTPException(status_code=400, detail="missing pkce verifier")

    if not settings.google_client_secret or not settings.google_client_id:
        demo_sub = "dev-local-demo-user"
        user = db.execute(select(User).where(User.google_sub == demo_sub)).scalar_one_or_none()
        if not user:
            user = User(
                google_sub=demo_sub,
                email="demo@example.com",
                name="Demo User"
            )
            db.add(user)
            db.commit()
            db.refresh(user)
        response = JSONResponse(content={"status": "stubbed"})
        _set_cookie(response, settings.session_cookie_name, str(user.id), request=request)
        return response

    try:
        token_json, token_status = _exchange_code_for_tokens(code, code_verifier)
    except HTTPException as exc:
        logger.warning("Google token exchange failed: %s", exc.detail)
        return RedirectResponse(
            url=f"{settings.frontend_url.rstrip('/')}/?auth_error=token_exchange_failed",
            status_code=302
        )

    token_key_flags = {
        "id_token": "id_token" in token_json,
        "access_token": "access_token" in token_json,
        "refresh_token": "refresh_token" in token_json,
        "token_type": "token_type" in token_json,
        "scope": "scope" in token_json
    }
    logger.info("Google token exchange response keys: %s", token_key_flags)

    id_token = token_json.get("id_token")
    if not id_token:
        logger.warning(
            "Google token response missing id_token (status=%s token_keys=%s)",
            token_status,
            list(token_json.keys())
        )
        return RedirectResponse(
            url=f"{settings.frontend_url.rstrip('/')}/?auth_error=id_token_missing",
            status_code=302
        )

    try:
        claims = _verify_id_token(id_token, list(token_json.keys()))
    except HTTPException as exc:
        logger.warning("Google id_token invalid: %s", exc.detail)
        return RedirectResponse(
            url=f"{settings.frontend_url.rstrip('/')}/?auth_error=id_token_invalid",
            status_code=302
        )
    email = claims.get("email")
    google_sub = claims.get("sub")
    if not google_sub:
        raise HTTPException(status_code=400, detail="missing subject")
    name = claims.get("name") or claims.get("given_name") or "User"

    user = db.execute(select(User).where(User.google_sub == google_sub)).scalar_one_or_none()
    if not user and email:
        user = db.execute(select(User).where(User.email == email)).scalar_one_or_none()

    if not user:
        user = User(google_sub=google_sub, email=email, name=name)
        db.add(user)
    else:
        user.google_sub = google_sub
        user.email = email
        user.name = name
    db.commit()
    db.refresh(user)

    redirect_url = f"{settings.frontend_url.rstrip('/')}/"
    response = RedirectResponse(url=redirect_url, status_code=302)
    _set_cookie(response, settings.session_cookie_name, str(user.id), request=request)
    response.delete_cookie("pkce_verifier")
    response.delete_cookie("oauth_state")
    return response


@app.get("/me")
def get_me(request: Request, db: Session = Depends(get_db)) -> dict[str, Any]:
    user = _get_user_from_cookie(db, request)
    if not user:
        raise HTTPException(status_code=401, detail="not authenticated")
    return {
        "id": str(user.id),
        "google_sub": user.google_sub,
        "email": user.email,
        "name": user.name,
        "is_premium": user.is_premium,
        "premium_until": user.premium_until,
    }


@app.post("/logout")
def logout() -> JSONResponse:
    response = JSONResponse(content={"status": "ok"})
    response.delete_cookie(settings.session_cookie_name)
    response.delete_cookie(BOOKING_SESSION_COOKIE_NAME)
    return response


@app.post("/therapists/search", response_model=TherapistSearchResponse)
def therapists_search(
    payload: TherapistSearchRequest,
    request: Request,
    db: Session = Depends(get_db)
) -> TherapistSearchResponse:
    user = _get_user_from_cookie(db, request)
    therapist_agent = _build_therapist_agent()
    if not user and not therapist_agent.dev_mode:
        raise HTTPException(status_code=401, detail="not authenticated")
    if user and not user.is_premium and not therapist_agent.dev_mode:
        raise HTTPException(status_code=403, detail="premium required")
    results, _ = therapist_agent.search_with_retries(
        location_text=payload.location_text,
        radius_km=payload.radius_km,
        specialty=None,
        limit=payload.limit,
    )
    therapist_agent.remember_location(user=user, request=request, location=payload.location_text)
    return TherapistSearchResponse(results=results)


@app.post("/chat", response_model=ChatResponse)
def chat(
    payload: ChatRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
) -> ChatResponse:
    # --- Correlation ID for this request ---
    correlation_id = new_correlation_id()
    set_correlation_id(correlation_id)

    message = payload.message.strip()
    user = _get_user_from_cookie(db, request)
    session_key = _get_session_key(user, request)

    # --- Rate limiting ---
    client_key = (
        request.cookies.get(settings.session_cookie_name)
        or (request.client.host if request.client else "unknown")
    )
    try:
        _rate_limiter.check(client_key)
    except RateLimitExceeded:
        log_event("rate_limit_exceeded", client_key=client_key, correlation_id=correlation_id)
        raise HTTPException(
            status_code=429,
            detail="Too many requests. Please wait a moment before sending another message."
        )

    # --- Safety gate FIRST (crisis / jailbreak via SafetyGate) ---
    # Must run before scope_check so that crisis messages are never blocked as out-of-scope.
    actor_key = _get_booking_actor_key(user, request)
    pending_action = None
    pending_expired = False
    if actor_key:
        pending_action, pending_expired = load_pending_booking(db, actor_key)

    therapist_agent = _build_therapist_agent()
    safety_gate = SafetyGate(therapist_agent=therapist_agent)
    safety_response = safety_gate.handle(user=user, request=request, message=message)
    if safety_response:
        log_event("safety_trigger", trigger_type="safety_gate", correlation_id=correlation_id)
        _append_to_history(session_key, message, safety_response.coach_message or "")
        return safety_response

    # --- Jailbreak guardrail ---
    if contains_jailbreak_attempt(message):
        log_event("safety_trigger", trigger_type="jailbreak", correlation_id=correlation_id)
        jailbreak_response = ChatResponse(
            coach_message=(
                "I can't follow attempts to bypass safety boundaries. "
                "I'm here to help with mental health coping skills, finding therapists, "
                "or booking appointments — nothing outside that scope."
            )
        )
        _append_to_history(session_key, message, jailbreak_response.coach_message or "")
        return jailbreak_response

    # --- Scope check — only after safety/crisis is already handled ---
    if not scope_check(message):
        log_event("safety_trigger", trigger_type="out_of_scope", correlation_id=correlation_id)
        out_of_scope_response = ChatResponse(
            coach_message=(
                "I'm here to help with mental health coping skills, finding therapists, "
                "or booking appointments. I'm not able to help with that — "
                "is there something in those areas I can support you with?"
            )
        )
        _append_to_history(session_key, message, out_of_scope_response.coach_message or "")
        return out_of_scope_response

    # --- Load conversation history for context ---
    history = _load_history(session_key)

    # Note: emotional state messages (anxious, stressed, sad, etc.) are intentionally
    # routed through run_agent() below so the LLM can respond with full conversation
    # history context — giving contextually-aware, non-repetitive coping guidance.

    if is_prescription_request(message):
        log_event("safety_trigger", trigger_type="prescription", correlation_id=correlation_id)
        prescription_response = route_message(message)
        _append_to_history(session_key, message, prescription_response.coach_message or "")
        return prescription_response

    router = _build_router()
    route = router.route(
        RouterInput(
            message=message,
            has_pending_booking=bool(pending_action),
            has_pending_therapist_location=therapist_agent.has_pending_location_request(
                user=user,
                request=request,
            ),
        )
    )
    log_event(
        "agent_routing",
        route=route,
        has_pending_booking=bool(pending_action),
        has_pending_location=therapist_agent.has_pending_location_request(user=user, request=request),
        user_id=str(user.id) if user else None,
        correlation_id=correlation_id,
    )

    if route == "THERAPIST_SEARCH":
        therapist_response = therapist_agent.handle(user=user, request=request, message=message)
        _append_to_history(session_key, message, therapist_response.coach_message or "")
        return therapist_response

    if route == "BOOKING_EMAIL":
        if not actor_key:
            actor_key = _ensure_booking_actor_key(user, request, response)
        booking_agent = _build_booking_agent()
        booking_response = booking_agent.handle(
            db=db,
            user=user,
            actor_key=actor_key,
            message=message,
            pending_action=pending_action,
            pending_expired=pending_expired,
        )
        if booking_response:
            _append_to_history(session_key, message, booking_response.coach_message or "")
            return booking_response

    # --- COACH: pass conversation history for context continuity ---
    with Timer() as t:
        response_json = run_agent(message, history=history)
    log_event("llm_call", route="COACH", duration_ms=round(t.elapsed_ms), correlation_id=correlation_id)

    final_response = ChatResponse(**response_json)
    _append_to_history(session_key, message, final_response.coach_message or "")
    return final_response


@app.post("/payments/create-checkout-session", response_model=CheckoutSessionResponse)
def create_checkout_session(request: Request, db: Session = Depends(get_db)) -> CheckoutSessionResponse:
    user = _get_user_from_cookie(db, request)
    if not user:
        raise HTTPException(status_code=401, detail="not authenticated")

    if not settings.stripe_secret_key or not settings.stripe_price_id:
        return CheckoutSessionResponse(url="https://checkout.stripe.com/test/session")

    stripe.api_key = settings.stripe_secret_key
    frontend_base = settings.frontend_url.rstrip("/")
    session = stripe.checkout.Session.create(
        mode="payment",
        line_items=[{"price": settings.stripe_price_id, "quantity": 1}],
        success_url=f"{frontend_base}/premium/success?session_id={{CHECKOUT_SESSION_ID}}",
        cancel_url=f"{frontend_base}/premium/cancel",
        client_reference_id=str(user.id),
        metadata={"user_id": str(user.id)}
    )
    return CheckoutSessionResponse(url=session.url)


@app.get("/payments/session/{session_id}")
def get_checkout_session(
    session_id: str,
    request: Request,
    db: Session = Depends(get_db)
) -> dict[str, Any]:
    user = _get_user_from_cookie(db, request)
    if not user:
        raise HTTPException(status_code=401, detail="not authenticated")
    if not settings.stripe_secret_key:
        raise HTTPException(status_code=501, detail="stripe not configured")

    stripe.api_key = settings.stripe_secret_key
    session = stripe.checkout.Session.retrieve(session_id)
    metadata = session.get("metadata") or {}
    user_id = metadata.get("user_id") or session.get("client_reference_id")
    if user_id and str(user.id) != str(user_id):
        raise HTTPException(status_code=403, detail="forbidden")
    return {
        "id": session.get("id"),
        "status": session.get("status"),
        "payment_status": session.get("payment_status")
    }

@app.post("/payments/webhook")
async def stripe_webhook(request: Request, db: Session = Depends(get_db)) -> dict[str, str]:
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature", "")

    if settings.stripe_webhook_secret:
        try:
            event = stripe.Webhook.construct_event(payload, sig_header, settings.stripe_webhook_secret)
        except stripe.error.SignatureVerificationError as exc:
            raise HTTPException(status_code=400, detail="invalid signature") from exc
    else:
        event = json.loads(payload.decode("utf-8"))

    event_id = event.get("id")
    if not event_id:
        raise HTTPException(status_code=400, detail="missing event id")

    existing = db.execute(select(StripeEvent).where(StripeEvent.stripe_event_id == event_id)).scalar_one_or_none()
    if existing:
        return {"status": "already_processed"}

    db.add(StripeEvent(stripe_event_id=event_id))

    if event.get("type") == "checkout.session.completed":
        session = event.get("data", {}).get("object", {})
        metadata = session.get("metadata", {})
        user_id = metadata.get("user_id") or session.get("client_reference_id")
        parsed_user_id = _parse_user_id(user_id)
        if parsed_user_id:
            user = db.get(User, parsed_user_id)
            if user:
                user.is_premium = True
                stripe_customer_id = session.get("customer")
                if isinstance(stripe_customer_id, str) and stripe_customer_id.strip():
                    user.stripe_customer_id = stripe_customer_id.strip()

    db.commit()
    return {"status": "processed"}
