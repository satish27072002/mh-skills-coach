from pathlib import Path

from app import db
from app.ingest import chunk_text, ingest_paths


def test_chunk_text_overlap():
    text_value = "a" * 3200
    chunks = chunk_text(text_value, chunk_size=1500, overlap=200)
    assert len(chunks) == 3
    assert chunks[0][-200:] == chunks[1][:200]
    assert chunks[1][-200:] == chunks[2][:200]


def test_retrieve_similar_chunks_uses_embeddings(monkeypatch):
    calls = {"embedding": 0, "params": None}

    def embed_stub(message: str):
        calls["embedding"] += 1
        return [0.1, 0.2, 0.3]

    class FakeResult:
        def fetchall(self):
            return [("chunk text", {"meta": "x"})]

    class FakeConn:
        def execute(self, _query, params):
            calls["params"] = params
            return FakeResult()

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    class FakeEngine:
        class Dialect:
            name = "postgresql"

        dialect = Dialect()

        def connect(self):
            return FakeConn()

    monkeypatch.setattr(db, "engine", FakeEngine())
    results = db.retrieve_similar_chunks("hello", top_k=1, embedding_fn=embed_stub)

    assert calls["embedding"] == 1
    assert calls["params"] == {"embedding": "[0.100000,0.200000,0.300000]", "limit": 1}
    assert results == [{"text": "chunk text", "metadata": {"meta": "x"}}]


def test_ingest_calls_embeddings_and_inserts(tmp_path, monkeypatch):
    sample = tmp_path / "sample.txt"
    sample.write_text("hello world " * 200, encoding="utf-8")

    calls = {"embed": 0, "chunk_inserts": 0}

    def embed_stub(_text):
        calls["embed"] += 1
        return [0.1, 0.2, 0.3]

    class FakeResult:
        def scalar_one(self):
            return 1

    class FakeConn:
        def execute(self, query, params=None):
            if "INSERT INTO chunks" in str(query):
                calls["chunk_inserts"] += 1
                assert "embedding" in params
            if "INSERT INTO documents" in str(query):
                return FakeResult()
            return FakeResult()

    class FakeBegin:
        def __enter__(self):
            return FakeConn()

        def __exit__(self, exc_type, exc, tb):
            return False

    class FakeEngine:
        def begin(self):
            return FakeBegin()

    monkeypatch.setattr(db, "engine", FakeEngine())
    monkeypatch.setattr(db, "init_db", lambda: None)

    inserted = ingest_paths(tmp_path, reset=True, embed_fn=embed_stub)

    assert inserted == calls["chunk_inserts"]
    assert calls["embed"] == calls["chunk_inserts"]
