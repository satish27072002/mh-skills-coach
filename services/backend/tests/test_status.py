from fastapi.testclient import TestClient

from app import db
import app.main as main


def test_status_endpoint_returns_mode_and_pgvector_flag(monkeypatch):
    monkeypatch.setattr(main, "pgvector_ready", lambda: False)
    monkeypatch.setattr(
        main.httpx,
        "get",
        lambda *args, **kwargs: (_ for _ in ()).throw(main.httpx.ConnectError("no"))
    )
    client = TestClient(main.app)

    response = client.get("/status")

    assert response.status_code == 200
    payload = response.json()
    assert payload["agent_mode"] == "deterministic"
    assert payload["ollama_reachable"] is False
    assert payload["pgvector_ready"] is False
    assert payload["model"] is None
    assert "reason" in payload


def test_status_switches_when_ollama_and_pgvector_ready(monkeypatch):
    class DummyResponse:
        status_code = 200

    monkeypatch.setattr(main, "pgvector_ready", lambda: True)
    monkeypatch.setattr(main.httpx, "get", lambda *args, **kwargs: DummyResponse())
    client = TestClient(main.app)

    response = client.get("/status")

    assert response.status_code == 200
    payload = response.json()
    assert payload["ollama_reachable"] is True
    assert payload["pgvector_ready"] is True
    assert payload["agent_mode"] == "llm_rag"
    assert payload["model"] is not None


def test_pgvector_ready_true_when_extension_and_tables_exist():
    if db.engine.dialect.name != "postgresql":
        return
    db.init_db()
    assert db.pgvector_ready() is True
