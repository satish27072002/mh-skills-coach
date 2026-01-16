from fastapi.testclient import TestClient

from app import db, mcp_client
from app.config import settings
from app.main import app
from app.models import User


class DummyResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self):
        return self._payload


def test_therapist_intent_calls_mcp(monkeypatch):
    original_db_url = str(db.engine.url)
    db.reset_engine("sqlite+pysqlite:///./test_therapist_tool.db")
    db.init_db()
    try:
        with db.SessionLocal() as session:
            session.query(User).delete()
            user = User(email="pro@example.com", name="Pro User", is_premium=True)
            session.add(user)
            session.commit()
            session.refresh(user)

        called = {}

        def fake_post(url, json, timeout):
            called["url"] = url
            called["json"] = json
            return DummyResponse(
                {
                    "result": {
                        "therapists": [
                            {
                                "name": "Mindler",
                                "address": "Main St",
                                "url": "https://www.mindler.se/",
                                "phone": "+46 8 000 000",
                                "distance_km": 1.2
                            }
                        ]
                    }
                }
            )

        monkeypatch.setattr(settings, "mcp_base_url", "http://mcp.test")
        monkeypatch.setattr(mcp_client.httpx, "post", fake_post)

        client = TestClient(app)
        client.cookies.set(settings.session_cookie_name, str(user.id))
        response = client.post("/chat", json={"message": "find a therapist"})

        assert response.status_code == 200
        payload = response.json()
        assert payload["therapists"][0]["name"] == "Mindler"
        assert payload["therapists"][0]["url"] == "https://www.mindler.se/"
        assert called["url"].endswith("/tools/booking.search_therapists")
    finally:
        db.reset_engine(original_db_url)
