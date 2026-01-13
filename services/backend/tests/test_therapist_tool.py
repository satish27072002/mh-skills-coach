import os

os.environ["DATABASE_URL"] = "sqlite+pysqlite:///./test.db"
os.environ["MCP_BASE_URL"] = "http://mcp.test"

from fastapi.testclient import TestClient

from app import mcp_client
from app.main import app


class DummyResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self):
        return self._payload


def test_therapist_intent_calls_mcp(monkeypatch):
    called = {}

    def fake_post(url, json, timeout):
        called["url"] = url
        called["json"] = json
        return DummyResponse(
            {
                "result": {
                    "providers": [
                        {
                            "title": "Mindler",
                            "url": "https://www.mindler.se/",
                            "description": "Curated licensed platform with transparent intake."
                        }
                    ]
                }
            }
        )

    monkeypatch.setattr(mcp_client.httpx, "post", fake_post)

    client = TestClient(app)
    response = client.post("/chat", json={"message": "find a therapist"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["resources"][0]["title"] == "Mindler"
    assert payload["resources"][0]["url"] == "https://www.mindler.se/"
    assert payload["resources"][0]["description"]
    assert called["url"].endswith("/tools/booking.suggest_providers")
