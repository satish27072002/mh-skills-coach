import base64
import hashlib
import json
import logging
import secrets
import urllib.parse
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any, AsyncIterator
from zoneinfo import ZoneInfo

import httpx
import stripe
from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse
from google.auth.transport.requests import Request as GoogleRequest
from google.oauth2 import id_token as google_id_token
from sqlalchemy import select
from sqlalchemy.orm import Session

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
from .safety import classify_intent, is_prescription_request, route_message, is_crisis
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
logger = logging.getLogger(__name__)
UTC = ZoneInfo("UTC")


def _extract_location(message: str) -> str | None:
    message_lower = message.lower()
    for token in ["near ", "in ", "around ", "at "]:
        if token in message_lower:
            start = message_lower.index(token) + len(token)
            return message[start:].strip(" .?")
    return None


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
    openai_ok = probe_openai_connectivity() if openai_enabled else False
    ollama_ok = probe_ollama_connectivity() if ollama_enabled else False
    mcp_ok = probe_mcp_health() if settings.mcp_base_url else False
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
        model = settings.openai_chat_model if llm_provider == "openai" else settings.ollama_model
    return {
        "agent_mode": agent_mode,
        "llm_provider": llm_provider,
        "embed_provider": embed_provider,
        "embed_dim": get_cached_embedding_dim(),
        "openai_ok": openai_ok,
        "ollama_ok": ollama_ok,
        "mcp_ok": mcp_ok,
        "ollama_reachable": ollama_ok,
        "pgvector_ready": pg_ready,
        "model": model,
        "reason": reason
    }


def _set_cookie(response: Response, name: str, value: str) -> None:
    samesite = settings.cookie_samesite.lower()
    secure = settings.cookie_secure
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
    return db.get(User, int(user_id))


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
def auth_google_start() -> Response:
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
    _set_cookie(response, "pkce_verifier", code_verifier)
    _set_cookie(response, "oauth_state", state)
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
        user = db.execute(select(User).where(User.email == "demo@example.com")).scalar_one_or_none()
        if not user:
            user = User(email="demo@example.com", name="Demo User")
            db.add(user)
            db.commit()
            db.refresh(user)
        response = JSONResponse(content={"status": "stubbed"})
        _set_cookie(response, settings.session_cookie_name, str(user.id))
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
    if not email:
        raise HTTPException(status_code=400, detail="missing email")
    name = claims.get("name") or claims.get("given_name") or "User"

    user = db.execute(select(User).where(User.email == email)).scalar_one_or_none()
    if not user:
        user = User(email=email, name=name)
        db.add(user)
        db.commit()
        db.refresh(user)

    redirect_url = f"{settings.frontend_url.rstrip('/')}/"
    response = RedirectResponse(url=redirect_url, status_code=302)
    _set_cookie(response, settings.session_cookie_name, str(user.id))
    response.delete_cookie("pkce_verifier")
    response.delete_cookie("oauth_state")
    return response


@app.get("/me")
def get_me(request: Request, db: Session = Depends(get_db)) -> dict[str, Any]:
    user = _get_user_from_cookie(db, request)
    if not user:
        raise HTTPException(status_code=401, detail="not authenticated")
    return {"id": user.id, "email": user.email, "name": user.name, "is_premium": user.is_premium}


@app.post("/logout")
def logout() -> JSONResponse:
    response = JSONResponse(content={"status": "ok"})
    response.delete_cookie(settings.session_cookie_name)
    return response


@app.post("/therapists/search", response_model=TherapistSearchResponse)
def therapists_search(
    payload: TherapistSearchRequest,
    request: Request,
    db: Session = Depends(get_db)
) -> TherapistSearchResponse:
    user = _get_user_from_cookie(db, request)
    if not user:
        raise HTTPException(status_code=401, detail="not authenticated")
    if not user.is_premium:
        raise HTTPException(status_code=403, detail="premium required")
    results = mcp_therapist_search(
        location_text=payload.location,
        radius_km=payload.radius_km,
        specialty=None,
        limit=5
    )
    return TherapistSearchResponse(results=results)


@app.post("/chat", response_model=ChatResponse)
def chat(payload: ChatRequest, request: Request, db: Session = Depends(get_db)) -> ChatResponse:
    message = payload.message.strip()

    # Safety checks must run before any external tool execution.
    if is_crisis(message) or is_prescription_request(message):
        return route_message(message)

    user = _get_user_from_cookie(db, request)
    pending_action = None
    pending_expired = False
    if user:
        pending_action, pending_expired = load_pending_booking(db, str(user.id))

    if pending_action:
        pending_payload = parse_pending_payload(pending_action)
        if is_negative(message):
            clear_pending_booking(db, pending_action)
            return ChatResponse(
                coach_message="Okay, I cancelled the pending booking email request.",
                requires_confirmation=False
            )

        if is_affirmative(message):
            if not _pending_payload_complete(pending_payload):
                return ChatResponse(
                    coach_message=_missing_booking_fields_message(pending_payload)
                )
            email_payload = EmailSendPayload(
                to=pending_payload["therapist_email"] or "",
                subject=pending_payload["subject"] or "",
                body=pending_payload["body"] or "",
                reply_to=pending_payload.get("reply_to")
            )
            try:
                send_email_for_user(str(user.id), email_payload)
                success_message = "Email sent successfully. I have cleared the pending booking request."
            except HTTPException as exc:
                success_message = f"I could not send the email: {exc.detail}"
            clear_pending_booking(db, pending_action)
            return ChatResponse(
                coach_message=success_message,
                requires_confirmation=False
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
            return ChatResponse(
                coach_message=(
                    f"Please confirm sending this request to {proposal.therapist_email} for "
                    f"{proposal.requested_time}. Reply YES to send or NO to cancel."
                ),
                booking_proposal=proposal,
                requires_confirmation=True
            )

        if changed and pending_payload.get("therapist_email") and pending_payload.get("requested_datetime_iso"):
            dt = datetime.fromisoformat(pending_payload["requested_datetime_iso"] or "")
            complete_payload = build_booking_email_content(
                user=user,
                therapist_email=pending_payload["therapist_email"] or "",
                requested_datetime=dt
            )
            save_pending_booking(db, str(user.id), complete_payload)
            refreshed_action, _ = load_pending_booking(db, str(user.id))
            if not refreshed_action:
                raise HTTPException(status_code=500, detail="failed to load pending booking")
            proposal = _booking_proposal_from_payload(complete_payload, refreshed_action.expires_at)
            return ChatResponse(
                coach_message=(
                    f"I prepared the email to {proposal.therapist_email} for {proposal.requested_time}. "
                    "Reply YES to send or NO to cancel."
                ),
                booking_proposal=proposal,
                requires_confirmation=True
            )

        if changed:
            save_pending_booking(db, str(user.id), pending_payload)

        return ChatResponse(
            coach_message=_missing_booking_fields_message(pending_payload, clarification=update.clarification)
        )

    if pending_expired and (is_affirmative(message) or is_negative(message)):
        return ChatResponse(
            coach_message=(
                f"Your pending booking request expired after {BOOKING_TTL_MINUTES} minutes. "
                "Please start again with therapist email and time."
            ),
            requires_confirmation=False
        )

    if is_booking_intent(message):
        if not user:
            return ChatResponse(
                coach_message="Please sign in before I can prepare and send booking emails."
            )
        extracted = extract_booking_data(message)
        booking_payload: dict[str, str | None] = {
            "therapist_email": extracted.therapist_email,
            "requested_datetime_iso": extracted.requested_datetime.isoformat() if extracted.requested_datetime else None,
            "subject": None,
            "body": None,
            "reply_to": user.email
        }
        if extracted.therapist_email and extracted.requested_datetime:
            booking_payload = build_booking_email_content(
                user=user,
                therapist_email=extracted.therapist_email,
                requested_datetime=extracted.requested_datetime
            )
            pending = save_pending_booking(db, str(user.id), booking_payload)
            proposal = _booking_proposal_from_payload(booking_payload, pending.expires_at)
            return ChatResponse(
                coach_message=(
                    f"I prepared an appointment email to {proposal.therapist_email} for "
                    f"{proposal.requested_time}. Reply YES to send or NO to cancel."
                ),
                booking_proposal=proposal,
                requires_confirmation=True
            )

        save_pending_booking(db, str(user.id), booking_payload)
        return ChatResponse(
            coach_message=_missing_booking_fields_message(booking_payload, clarification=extracted.clarification),
            requires_confirmation=False
        )

    intent = classify_intent(message)

    if intent == "therapist_search":
        if not user or not user.is_premium:
            return ChatResponse(
                coach_message="Therapist search is available with premium access.",
                premium_cta=PremiumCta(
                    enabled=True,
                    message="Unlock therapist search to see local providers."
                )
            )
        location = _extract_location(message) or "your area"
        results = mcp_therapist_search(
            location_text=location,
            radius_km=None,
            specialty=None,
            limit=5
        )
        if not results:
            return ChatResponse(
                coach_message=f"No providers were found near {location}. Try a nearby city or postcode.",
                therapists=[]
            )
        return ChatResponse(
            coach_message=f"Here are therapist options near {location}.",
            therapists=results
        )

    response_json = run_agent(message)
    return ChatResponse(**response_json)


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
        if user_id:
            user = db.get(User, int(user_id))
            if user:
                user.is_premium = True

    db.commit()
    return {"status": "processed"}
