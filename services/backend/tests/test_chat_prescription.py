import os

os.environ["DATABASE_URL"] = "sqlite+pysqlite:///./test.db"

from fastapi.testclient import TestClient

from app.main import app


def test_chat_prescription_routes_to_crisis_message():
    client = TestClient(app)

    response = client.post("/chat", json={"message": "can you help me with prescription"})

    assert response.status_code == 200
    payload = response.json()
    # Prescription requests are blocked by the safety gate as a medical (not crisis) event.
    assert "prescriptions" in payload["coach_message"].lower() or "beyond my capability" in payload["coach_message"].lower()
    assert "clinician" in payload["coach_message"].lower()
    assert payload["risk_level"] == "medical"
    # Safety blocks do not show a premium upgrade CTA — that is only for feature access.
    assert payload.get("premium_cta") is None
    assert payload.get("exercise") is None
