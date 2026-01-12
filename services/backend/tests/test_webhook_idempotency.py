import os

os.environ["DATABASE_URL"] = "sqlite+pysqlite:///./test.db"

from fastapi.testclient import TestClient

from app.db import init_db, SessionLocal
from app.main import app
from app.models import StripeEvent


def test_webhook_idempotency():
    init_db()
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

    with SessionLocal() as db:
        events = db.query(StripeEvent).all()
        assert len(events) == 1
