from fastapi.testclient import TestClient

from app import db
from app.main import app
from app.models import StripeEvent


def test_webhook_idempotency():
    db.init_db()
    with db.SessionLocal() as session:
        session.query(StripeEvent).delete()
        session.commit()
    client = TestClient(app)

    payload = {
        "id": "evt_test_123",
        "type": "checkout.session.completed",
        "data": {"object": {"metadata": {"user_id": "999"}}}
    }

    first = client.post("/payments/webhook", json=payload)
    assert first.status_code == 200
    assert first.json()["status"] == "processed"

    second = client.post("/payments/webhook", json=payload)
    assert second.status_code == 200
    assert second.json()["status"] == "already_processed"

    with db.SessionLocal() as session:
        events = session.query(StripeEvent).all()
        assert len(events) == 1
