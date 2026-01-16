import pytest
import stripe
from fastapi.testclient import TestClient

from app import db
from app.config import settings
from app.main import app
from app.models import User


ORIGINAL_DATABASE_URL = str(db.engine.url)


@pytest.fixture()
def test_db():
    db.reset_engine("sqlite+pysqlite:///./test_checkout.db")
    db.init_db()
    with db.SessionLocal() as session:
        session.query(User).delete()
        session.commit()
    yield
    db.reset_engine(ORIGINAL_DATABASE_URL)


def test_create_checkout_session_returns_url(test_db, monkeypatch):
    monkeypatch.setattr(settings, "stripe_secret_key", "sk_test")
    monkeypatch.setattr(settings, "stripe_price_id", "price_test")

    with db.SessionLocal() as session:
        user = User(email="buyer@example.com", name="Buyer", is_premium=False)
        session.add(user)
        session.commit()
        session.refresh(user)

    def fake_create(**kwargs):
        class DummySession:
            url = "https://checkout.stripe.com/test/session"

        assert kwargs["client_reference_id"] == str(user.id)
        assert kwargs["metadata"]["user_id"] == str(user.id)
        return DummySession()

    monkeypatch.setattr(stripe.checkout.Session, "create", fake_create)
    client = TestClient(app)
    client.cookies.set(settings.session_cookie_name, str(user.id))
    response = client.post("/payments/create-checkout-session")

    assert response.status_code == 200
    assert response.json()["url"] == "https://checkout.stripe.com/test/session"


def test_get_checkout_session_requires_auth(test_db, monkeypatch):
    monkeypatch.setattr(settings, "stripe_secret_key", "sk_test")
    client = TestClient(app)
    response = client.get("/payments/session/sess_123")

    assert response.status_code == 401


def test_get_checkout_session_returns_status(test_db, monkeypatch):
    monkeypatch.setattr(settings, "stripe_secret_key", "sk_test")
    with db.SessionLocal() as session:
        user = User(email="viewer@example.com", name="Viewer", is_premium=False)
        session.add(user)
        session.commit()
        session.refresh(user)

    def fake_retrieve(_session_id):
        return {
            "id": "sess_123",
            "status": "complete",
            "payment_status": "paid",
            "metadata": {"user_id": str(user.id)}
        }

    monkeypatch.setattr(stripe.checkout.Session, "retrieve", fake_retrieve)
    client = TestClient(app)
    client.cookies.set(settings.session_cookie_name, str(user.id))
    response = client.get("/payments/session/sess_123")

    assert response.status_code == 200
    payload = response.json()
    assert payload["payment_status"] == "paid"
