from fastapi.testclient import TestClient

from app.main import app


def test_booking_search_therapists_shape():
    client = TestClient(app)
    response = client.post("/tools/booking.search_therapists", json={"params": {"location": "Stockholm"}})

    assert response.status_code == 200
    payload = response.json()["result"]
    assert "therapists" in payload
    assert len(payload["therapists"]) >= 1
    first = payload["therapists"][0]
    assert "name" in first
    assert "address" in first
    assert "url" in first
    assert "phone" in first
    assert "distance_km" in first
