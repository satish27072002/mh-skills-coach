import httpx

from app.embeddings import get_embedding


def test_get_embedding_retries(monkeypatch):
    calls = {"count": 0}

    class DummyResponse:
        def __init__(self, payload):
            self._payload = payload

        def raise_for_status(self):
            return None

        def json(self):
            return self._payload

    def fake_post(*args, **kwargs):
        calls["count"] += 1
        if calls["count"] < 3:
            raise httpx.ReadTimeout("timeout")
        return DummyResponse({"embedding": [0.1, 0.2]})

    monkeypatch.setattr(httpx, "post", fake_post)

    embedding = get_embedding("hello")

    assert embedding == [0.1, 0.2]
    assert calls["count"] == 3
