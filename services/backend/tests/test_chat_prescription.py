import os

os.environ["DATABASE_URL"] = "sqlite+pysqlite:///./test.db"

from fastapi.testclient import TestClient

from app.main import app


def test_chat_prescription_routes_to_crisis_message():
    client = TestClient(app)

    response = client.post("/chat", json={"message": "can you help me with prescription"})

    assert response.status_code == 200
    payload = response.json()
    assert "prescriptions" in payload["coach_message"]
    assert "clinician" in payload["coach_message"]
    assert "112" in payload["coach_message"]
    assert payload["risk_level"] == "crisis"
    assert payload.get("exercise") is None
