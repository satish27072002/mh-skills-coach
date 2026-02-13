from fastapi.testclient import TestClient

from app.main import app


def test_therapist_search_tool_success(monkeypatch):
    captured: dict[str, object] = {}

    def stub_search(**kwargs):
        captured.update(kwargs)
        return [
            {
                "name": "Calm Clinic",
                "address": "1 Main St",
                "distance_km": 1.2,
                "phone": "+46 8 123 000",
                "email": None,
                "source_url": "https://example.com"
            }
        ]

    monkeypatch.setattr(
        "app.main.therapist_search",
        stub_search
    )
    client = TestClient(app)

    response = client.post(
        "/tools/therapist_search",
        json={"location_text": "Stockholm", "radius_km": 5, "limit": 5}
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["results"][0]["name"] == "Calm Clinic"
    assert captured["specialty"] is None


def test_therapist_search_tool_allows_empty_specialty(monkeypatch):
    captured: dict[str, object] = {}

    def stub_search(**kwargs):
        captured.update(kwargs)
        return [
            {
                "name": "Calm Clinic",
                "address": "1 Main St",
                "distance_km": 1.2,
                "phone": "+46 8 123 000",
                "email": None,
                "source_url": "https://example.com"
            }
        ]

    monkeypatch.setattr("app.main.therapist_search", stub_search)
    client = TestClient(app)

    response = client.post(
        "/tools/therapist_search",
        json={"location_text": "Stockholm", "radius_km": 5, "specialty": "", "limit": 5}
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert captured["specialty"] is None

    response_ws = client.post(
        "/tools/therapist_search",
        json={"location_text": "Stockholm", "radius_km": 5, "specialty": "   ", "limit": 5}
    )
    assert response_ws.status_code == 200
    assert response_ws.json()["ok"] is True
    assert captured["specialty"] is None

    response_null = client.post(
        "/tools/therapist_search",
        json={"location_text": "Stockholm", "radius_km": 5, "specialty": None, "limit": 5}
    )
    assert response_null.status_code == 200
    assert response_null.json()["ok"] is True
    assert captured["specialty"] is None


def test_therapist_search_tool_with_specialty(monkeypatch):
    captured: dict[str, object] = {}

    def stub_search(**kwargs):
        captured.update(kwargs)
        return [
            {
                "name": "Anxiety Clinic",
                "address": "2 Main St",
                "distance_km": 1.5,
                "phone": "+46 8 123 001",
                "email": None,
                "source_url": "https://example.com/anxiety"
            }
        ]

    monkeypatch.setattr("app.main.therapist_search", stub_search)
    client = TestClient(app)

    response = client.post(
        "/tools/therapist_search",
        json={"location_text": "Stockholm", "radius_km": 5, "specialty": "anxiety", "limit": 5}
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert captured["specialty"] == "anxiety"


def test_therapist_search_tool_invalid_argument():
    client = TestClient(app)

    response = client.post("/tools/therapist_search", json={"radius_km": 5})

    assert response.status_code == 400
    payload = response.json()
    assert payload["ok"] is False
    assert payload["error"]["code"] == "INVALID_ARGUMENT"


def test_send_email_success(monkeypatch):
    monkeypatch.setattr("app.main.send_email_via_smtp", lambda **kwargs: "<msg-1@example.com>")
    client = TestClient(app)

    response = client.post(
        "/tools/send_email",
        json={
            "to": "user@example.com",
            "subject": "Test",
            "body": "Hello"
        }
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["message_id"] == "<msg-1@example.com>"


def test_send_email_invalid_argument_bad_email():
    client = TestClient(app)

    response = client.post(
        "/tools/send_email",
        json={
            "to": "bad-email",
            "subject": "Test",
            "body": "Hello"
        }
    )

    assert response.status_code == 400
    payload = response.json()
    assert payload["ok"] is False
    assert payload["error"]["code"] == "INVALID_ARGUMENT"


def test_send_email_smtp_failure(monkeypatch):
    import smtplib

    def fail_send(**kwargs):
        raise smtplib.SMTPException("smtp failed")

    monkeypatch.setattr("app.main.send_email_via_smtp", fail_send)
    client = TestClient(app)

    response = client.post(
        "/tools/send_email",
        json={
            "to": "user@example.com",
            "subject": "Test",
            "body": "Hello"
        }
    )

    assert response.status_code == 502
    payload = response.json()
    assert payload["ok"] is False
    assert payload["error"]["code"] == "SMTP_ERROR"
