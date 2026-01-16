import base64
import hashlib
import json
import secrets
import urllib.parse
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator

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
from .db import get_db, init_db, pgvector_ready
from .mcp_client import search_therapists
from .models import StripeEvent, User
from .safety import classify_intent, route_message
from .schemas import (
    ChatRequest,
    ChatResponse,
    CheckoutSessionResponse,
    PremiumCta,
    TherapistSearchRequest,
    TherapistSearchResponse
)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    init_db()
    yield


app = FastAPI(title="mh-skills-backend", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://frontend:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"]
)

GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_ISSUERS = {"accounts.google.com", "https://accounts.google.com"}


def _extract_location(message: str) -> str | None:
    message_lower = message.lower()
    for token in ["near ", "in ", "around ", "at "]:
        if token in message_lower:
            start = message_lower.index(token) + len(token)
            return message[start:].strip(" .?")
    return None


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}

@app.get("/status")
def status() -> dict[str, Any]:
    pg_ready = pgvector_ready()
    ollama_reachable = False
    try:
        response = httpx.get(f"{settings.ollama_base_url}/api/tags", timeout=0.8)
        ollama_reachable = response.status_code == 200
    except httpx.HTTPError:
        ollama_reachable = False
    agent_mode = "llm_rag" if ollama_reachable and pg_ready else "deterministic"
    if not pg_ready:
        reason = "pgvector not ready"
    elif not ollama_reachable:
        reason = "Ollama not reachable"
    else:
        reason = "LLM+RAG ready"
    return {
        "agent_mode": agent_mode,
        "ollama_reachable": ollama_reachable,
        "pgvector_ready": pg_ready,
        "model": settings.ollama_model if ollama_reachable else None,
        "reason": reason
    }


def _set_cookie(response: JSONResponse, name: str, value: str) -> None:
    response.set_cookie(
        name,
        value,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax"
    )


def _get_user_from_cookie(db: Session, request: Request) -> User | None:
    user_id = request.cookies.get(settings.session_cookie_name)
    if not user_id:
        return None
    return db.get(User, int(user_id))


def _code_challenge(code_verifier: str) -> str:
    digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")


def _exchange_code_for_id_token(code: str, code_verifier: str) -> str:
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

    payload = response.json()
    id_token = payload.get("id_token")
    if not id_token:
        raise HTTPException(status_code=400, detail="missing id_token")
    return id_token


def _verify_id_token(id_token: str) -> dict[str, Any]:
    try:
        claims = google_id_token.verify_oauth2_token(
            id_token,
            GoogleRequest(),
            settings.google_client_id
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="invalid id_token") from exc

    if claims.get("iss") not in GOOGLE_ISSUERS:
        raise HTTPException(status_code=400, detail="invalid token issuer")
    return claims


@app.get("/auth/google/start")
def auth_google_start() -> JSONResponse:
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

    response = JSONResponse(content={"auth_url": auth_url})
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

    id_token = _exchange_code_for_id_token(code, code_verifier)
    claims = _verify_id_token(id_token)
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
    results = search_therapists(payload.location, payload.radius_km)
    return TherapistSearchResponse(results=results)


@app.post("/chat", response_model=ChatResponse)
def chat(payload: ChatRequest, request: Request, db: Session = Depends(get_db)) -> ChatResponse:
    intent = classify_intent(payload.message)

    if intent in {"crisis", "prescription"}:
        return route_message(payload.message)

    if intent == "therapist_search":
        user = _get_user_from_cookie(db, request)
        if not user or not user.is_premium:
            return ChatResponse(
                coach_message="Therapist search is available with premium access.",
                premium_cta=PremiumCta(
                    enabled=True,
                    message="Unlock therapist search to see local providers."
                )
            )
        location = _extract_location(payload.message) or "your area"
        results = search_therapists(location, None)
        return ChatResponse(
            coach_message=f"Here are therapist options near {location}.",
            therapists=results
        )

    response_json = run_agent(payload.message)
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
