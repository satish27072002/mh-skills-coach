import json

import pytest
import stripe
from fastapi.testclient import TestClient

from app import db
from app.config import settings
from app.main import app
from app.models import StripeEvent, User


ORIGINAL_DATABASE_URL = str(db.engine.url)


@pytest.fixture()
def test_db():
    db.reset_engine("sqlite+pysqlite:///./test_payments.db")
    db.init_db()
    with db.SessionLocal() as session:
        session.query(StripeEvent).delete()
        session.query(User).delete()
        session.commit()
    yield
    db.reset_engine(ORIGINAL_DATABASE_URL)


def test_webhook_idempotency(test_db, monkeypatch):
    settings.stripe_webhook_secret = "whsec_test"
    client = TestClient(app)

    payload = {
        "id": "evt_test_123",
        "type": "checkout.session.completed",
        "data": {"object": {"metadata": {"user_id": "999"}}}
    }

    def fake_construct_event(body, sig_header, secret):
        return payload

    monkeypatch.setattr(stripe.Webhook, "construct_event", fake_construct_event)

    first = client.post(
        "/payments/webhook",
        data=json.dumps(payload),
        headers={"stripe-signature": "sig"}
    )
    assert first.status_code == 200
    assert first.json()["status"] == "processed"

    second = client.post(
        "/payments/webhook",
        data=json.dumps(payload),
        headers={"stripe-signature": "sig"}
    )
    assert second.status_code == 200
    assert second.json()["status"] == "already_processed"

    with db.SessionLocal() as session:
        events = session.query(StripeEvent).all()
        assert len(events) == 1


def test_webhook_sets_premium_flag(test_db, monkeypatch):
    settings.stripe_webhook_secret = "whsec_test"
    with db.SessionLocal() as session:
        user = User(email="pay@example.com", name="Pay User", is_premium=False)
        session.add(user)
        session.commit()
        session.refresh(user)

    payload = {
        "id": "evt_test_456",
        "type": "checkout.session.completed",
        "data": {"object": {"metadata": {"user_id": str(user.id)}}}
    }

    monkeypatch.setattr(stripe.Webhook, "construct_event", lambda *args, **kwargs: payload)
    client = TestClient(app)
    response = client.post(
        "/payments/webhook",
        data=json.dumps(payload),
        headers={"stripe-signature": "sig"}
    )

    assert response.status_code == 200
    with db.SessionLocal() as session:
        refreshed = session.get(User, user.id)
        assert refreshed.is_premium is True


def test_webhook_signature_error_returns_400(test_db, monkeypatch):
    settings.stripe_webhook_secret = "whsec_test"

    def fake_construct_event(body, sig_header, secret):
        raise stripe.error.SignatureVerificationError("bad", sig_header)

    monkeypatch.setattr(stripe.Webhook, "construct_event", fake_construct_event)
    client = TestClient(app)
    response = client.post(
        "/payments/webhook",
        data=json.dumps({"id": "evt_bad"}),
        headers={"stripe-signature": "sig"}
    )

    assert response.status_code == 400
