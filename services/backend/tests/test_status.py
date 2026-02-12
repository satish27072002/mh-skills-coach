import logging

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

from app import db
import app.main as main
from app.config import settings
from app.llm.provider import ConfigurationError


def test_status_endpoint_returns_mode_and_pgvector_flag(monkeypatch):
    monkeypatch.setattr(settings, "llm_provider", "ollama")
    monkeypatch.setattr(settings, "embed_provider", "ollama")
    monkeypatch.setattr(settings, "embedding_dim", 768)
    monkeypatch.setattr(settings, "mcp_base_url", "http://mcp:7000")
    monkeypatch.setattr(main, "pgvector_ready", lambda: False)
    monkeypatch.setattr(main, "probe_ollama_connectivity", lambda *args, **kwargs: False)
    monkeypatch.setattr(main, "probe_mcp_health", lambda *args, **kwargs: True)
    client = TestClient(main.app)

    response = client.get("/status")

    assert response.status_code == 200
    payload = response.json()
    assert payload["agent_mode"] == "deterministic"
    assert payload["llm_provider"] == "ollama"
    assert payload["embed_provider"] == "ollama"
    assert payload["openai_ok"] is False
    assert payload["ollama_ok"] is False
    assert payload["mcp_ok"] is True
    assert payload["ollama_reachable"] is False
    assert payload["embed_dim"] == 768
    assert payload["pgvector_ready"] is False
    assert payload["model"] is None
    assert "reason" in payload


def test_status_switches_when_ollama_and_pgvector_ready(monkeypatch):
    monkeypatch.setattr(settings, "llm_provider", "ollama")
    monkeypatch.setattr(settings, "embed_provider", "ollama")
    monkeypatch.setattr(settings, "embedding_dim", 768)
    monkeypatch.setattr(settings, "mcp_base_url", "http://mcp:7000")
    monkeypatch.setattr(main, "pgvector_ready", lambda: True)
    monkeypatch.setattr(main, "probe_ollama_connectivity", lambda *args, **kwargs: True)
    monkeypatch.setattr(main, "probe_mcp_health", lambda *args, **kwargs: True)
    client = TestClient(main.app)

    response = client.get("/status")

    assert response.status_code == 200
    payload = response.json()
    assert payload["ollama_reachable"] is True
    assert payload["ollama_ok"] is True
    assert payload["openai_ok"] is False
    assert payload["mcp_ok"] is True
    assert payload["embed_dim"] == 768
    assert payload["pgvector_ready"] is True
    assert payload["agent_mode"] == "llm_rag"
    assert payload["model"] is not None


def test_status_switches_when_openai_and_pgvector_ready(monkeypatch):
    monkeypatch.setattr(settings, "llm_provider", "openai")
    monkeypatch.setattr(settings, "embed_provider", "openai")
    monkeypatch.setattr(settings, "embedding_dim", 1536)
    monkeypatch.setattr(settings, "openai_api_key", "test-key")
    monkeypatch.setattr(settings, "mcp_base_url", "http://mcp:7000")
    monkeypatch.setattr(main, "pgvector_ready", lambda: True)
    monkeypatch.setattr(main, "probe_openai_connectivity", lambda *args, **kwargs: True)
    monkeypatch.setattr(main, "probe_mcp_health", lambda *args, **kwargs: True)
    client = TestClient(main.app)

    response = client.get("/status")

    assert response.status_code == 200
    payload = response.json()
    assert payload["llm_provider"] == "openai"
    assert payload["embed_provider"] == "openai"
    assert payload["openai_ok"] is True
    assert payload["ollama_ok"] is False
    assert payload["mcp_ok"] is True
    assert payload["embed_dim"] == 1536
    assert payload["pgvector_ready"] is True
    assert payload["agent_mode"] == "llm_rag"
    assert payload["model"] == settings.openai_chat_model


def test_startup_fails_fast_for_openai_without_api_key(monkeypatch, caplog):
    monkeypatch.setattr(settings, "llm_provider", "openai")
    monkeypatch.setattr(settings, "embed_provider", "ollama")
    monkeypatch.setattr(settings, "openai_api_key", None)

    with caplog.at_level(logging.CRITICAL):
        with pytest.raises(ConfigurationError):
            with TestClient(main.app):
                pass
    assert any("Invalid provider configuration" in record.message for record in caplog.records)


def test_startup_fails_fast_on_embedding_dimension_mismatch(monkeypatch):
    monkeypatch.setattr(settings, "llm_provider", "ollama")
    monkeypatch.setattr(settings, "embed_provider", "ollama")
    monkeypatch.setattr(settings, "embedding_dim", 1536)
    monkeypatch.setattr(main, "init_db", lambda: None)
    monkeypatch.setattr(main, "ensure_embedding_dimension_compatible", lambda: (_ for _ in ()).throw(RuntimeError("mismatch")))

    with pytest.raises(RuntimeError, match="mismatch"):
        with TestClient(main.app):
            pass


def test_pgvector_ready_true_when_extension_and_tables_exist():
    if db.engine.dialect.name != "postgresql":
        return
    try:
        db.init_db()
    except OperationalError:
        pytest.skip("postgres not available for pgvector readiness check")
    assert db.pgvector_ready() is True
