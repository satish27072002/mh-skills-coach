import base64
import hashlib
import json
import secrets
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator

import stripe
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import settings
from .db import get_db, init_db
from .mcp_client import suggest_providers
from .models import StripeEvent, User
from .safety import is_crisis, is_medical_request, route_message
from .schemas import ChatRequest, ChatResponse, CheckoutSessionResponse


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

THERAPIST_KEYWORDS = [
    "therapist",
    "counselor",
    "counsellor",
    "professional help"
]


def _has_therapist_intent(message: str) -> bool:
    message_lower = message.lower()
    return any(keyword in message_lower for keyword in THERAPIST_KEYWORDS)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


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
def auth_google_callback(request: Request, db: Session = Depends(get_db)) -> JSONResponse:
    code = request.query_params.get("code")
    state = request.query_params.get("state")
    stored_state = request.cookies.get("oauth_state")

    if not code or not state or state != stored_state:
        raise HTTPException(status_code=400, detail="invalid oauth state")

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

    raise HTTPException(status_code=501, detail="oauth exchange not implemented")


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


@app.post("/chat", response_model=ChatResponse)
def chat(payload: ChatRequest) -> ChatResponse:
    if is_crisis(payload.message) or is_medical_request(payload.message):
        return route_message(payload.message)

    if _has_therapist_intent(payload.message):
        providers = suggest_providers()
        return ChatResponse(
            coach_message="Here are curated options for professional support.",
            resources=providers
        )

    return route_message(payload.message)


@app.post("/payments/create-checkout-session", response_model=CheckoutSessionResponse)
def create_checkout_session(request: Request, db: Session = Depends(get_db)) -> CheckoutSessionResponse:
    user = _get_user_from_cookie(db, request)
    if not user:
        raise HTTPException(status_code=401, detail="not authenticated")

    if not settings.stripe_secret_key or not settings.stripe_price_id:
        return CheckoutSessionResponse(url="https://checkout.stripe.com/test/session")

    stripe.api_key = settings.stripe_secret_key
    session = stripe.checkout.Session.create(
        mode="payment",
        line_items=[{"price": settings.stripe_price_id, "quantity": 1}],
        success_url="http://localhost:3000/premium/success",
        cancel_url="http://localhost:3000/premium/cancel",
        client_reference_id=str(user.id),
        metadata={"user_id": str(user.id)}
    )
    return CheckoutSessionResponse(url=session.url)


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
        user_id = metadata.get("user_id")
        if user_id:
            user = db.get(User, int(user_id))
            if user:
                user.is_premium = True

    db.commit()
    return {"status": "processed"}
