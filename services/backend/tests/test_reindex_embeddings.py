from app.scripts import reindex_embeddings as script


def test_reindex_embeddings_updates_all_chunks(monkeypatch):
    calls = {"null_reset": 0, "updates": 0}

    class FakeResult:
        def __init__(self, rows):
            self._rows = rows

        def fetchall(self):
            return self._rows

    class FakeConn:
        def execute(self, query, params=None):
            sql = str(query)
            if "SELECT id, text FROM chunks" in sql:
                return FakeResult([(1, "chunk 1"), (2, "chunk 2")])
            if "UPDATE chunks SET embedding = NULL" in sql:
                calls["null_reset"] += 1
                return FakeResult([])
            if "UPDATE chunks" in sql and "SET embedding" in sql:
                calls["updates"] += 1
                assert "embedding" in params
                assert "id" in params
                return FakeResult([])
            return FakeResult([])

    class FakeBegin:
        def __enter__(self):
            return FakeConn()

        def __exit__(self, exc_type, exc, tb):
            return False

    class FakeEngine:
        def begin(self):
            return FakeBegin()

    monkeypatch.setattr(script.db, "engine", FakeEngine())
    monkeypatch.setattr(script.db, "init_db", lambda: None)
    monkeypatch.setattr(script.db, "ensure_embedding_dimension_compatible", lambda: 3)
    monkeypatch.setattr(script, "get_active_embedding_dim", lambda: 3)
    monkeypatch.setattr(script, "get_embedding", lambda _text: [0.1, 0.2, 0.3])

    result = script.reindex_embeddings(log_every=1)

    assert result == {"total_chunks": 2, "updated_chunks": 2}
    assert calls["null_reset"] == 1
    assert calls["updates"] == 2


def test_reindex_embeddings_dimension_mismatch_raises(monkeypatch):
    class FakeResult:
        def __init__(self, rows):
            self._rows = rows

        def fetchall(self):
            return self._rows

    class FakeConn:
        def execute(self, query, params=None):
            if "SELECT id, text FROM chunks" in str(query):
                return FakeResult([(1, "chunk 1")])
            return FakeResult([])

    class FakeBegin:
        def __enter__(self):
            return FakeConn()

        def __exit__(self, exc_type, exc, tb):
            return False

    class FakeEngine:
        def begin(self):
            return FakeBegin()

    monkeypatch.setattr(script.db, "engine", FakeEngine())
    monkeypatch.setattr(script.db, "init_db", lambda: None)
    monkeypatch.setattr(script.db, "ensure_embedding_dimension_compatible", lambda: 1536)
    monkeypatch.setattr(script, "get_active_embedding_dim", lambda: 1536)
    monkeypatch.setattr(script, "get_embedding", lambda _text: [0.1, 0.2, 0.3])

    try:
        script.reindex_embeddings()
    except RuntimeError as exc:
        assert "does not match active dimension 1536" in str(exc)
    else:
        raise AssertionError("Expected RuntimeError for mismatched embedding dimension")
