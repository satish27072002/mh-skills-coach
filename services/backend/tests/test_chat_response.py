from fastapi.testclient import TestClient

from app.main import app


def test_chat_response_contains_coach_message():
    client = TestClient(app)
    response = client.post("/chat", json={"message": "Can you prescribe medication?"})

    assert response.status_code == 200
    payload = response.json()
    assert "coach_message" in payload
    if payload.get("exercise"):
        assert "type" in payload["exercise"]
        assert "steps" in payload["exercise"]
        assert "duration_seconds" in payload["exercise"]
