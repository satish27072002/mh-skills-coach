from typing import Any, Callable, Iterable

from sqlalchemy import create_engine, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from .config import settings
from .embed_dimension import get_active_embedding_dim
from .embeddings import get_embedding


class Base(DeclarativeBase):
    pass


def _make_engine(database_url: str):
    return create_engine(database_url, pool_pre_ping=True)


engine = _make_engine(settings.database_url)
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)


def init_db() -> None:
    from . import models

    if engine.dialect.name == "postgresql":
        active_dim = get_active_embedding_dim()
        with engine.begin() as conn:
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector;"))
            conn.execute(
                text(
                    """
                    CREATE TABLE IF NOT EXISTS documents (
                        id serial PRIMARY KEY,
                        source_id text UNIQUE,
                        title text,
                        url text,
                        year int,
                        doc_type text,
                        tags jsonb,
                        created_at timestamptz DEFAULT now()
                    );
                    """
                )
            )
            conn.execute(
                text(
                    f"""
                    CREATE TABLE IF NOT EXISTS chunks (
                        id serial PRIMARY KEY,
                        document_id int REFERENCES documents(id) ON DELETE CASCADE,
                        chunk_index int NOT NULL,
                        text text NOT NULL,
                        metadata jsonb,
                        embedding vector({active_dim}),
                        created_at timestamptz DEFAULT now(),
                        UNIQUE(document_id, chunk_index)
                    );
                    """
                )
            )
            conn.execute(
                text(
                    """
                    -- Dimension may change as embeddings evolve.
                    CREATE INDEX IF NOT EXISTS chunks_embedding_ivfflat_idx
                    ON chunks USING ivfflat (embedding) WITH (lists = 100);
                    """
                )
            )

    Base.metadata.create_all(bind=engine)


def reset_engine(database_url: str | None = None) -> None:
    global engine, SessionLocal
    engine.dispose()
    engine = _make_engine(database_url or settings.database_url)
    SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)


def pgvector_ready() -> bool:
    if engine.dialect.name != "postgresql":
        return False
    try:
        with engine.connect() as conn:
            ext = conn.execute(
                text("SELECT 1 FROM pg_extension WHERE extname = 'vector';")
            ).scalar()
            if not ext:
                return False
            rows = conn.execute(
                text(
                    """
                    SELECT table_name
                    FROM information_schema.tables
                    WHERE table_schema = 'public'
                    AND table_name IN ('documents', 'chunks');
                    """
                )
            ).fetchall()
            tables = {row[0] for row in rows}
            return "documents" in tables and "chunks" in tables
    except Exception:
        return False


def _vector_literal(values: Iterable[float]) -> str:
    return "[" + ",".join(f"{value:.6f}" for value in values) + "]"


def get_chunks_embedding_dim() -> int | None:
    if engine.dialect.name != "postgresql":
        return None
    with engine.connect() as conn:
        row = conn.execute(
            text(
                """
                SELECT a.atttypmod
                FROM pg_attribute a
                JOIN pg_class c ON c.oid = a.attrelid
                JOIN pg_namespace n ON n.oid = c.relnamespace
                WHERE n.nspname = 'public'
                  AND c.relname = 'chunks'
                  AND a.attname = 'embedding'
                  AND a.attnum > 0
                  AND NOT a.attisdropped
                LIMIT 1;
                """
            )
        ).fetchone()
    if not row:
        return None
    typmod = int(row[0])
    if typmod < 0:
        return None
    return typmod - 4


def ensure_embedding_dimension_compatible() -> int | None:
    if engine.dialect.name != "postgresql":
        return None
    active_dim = get_active_embedding_dim()
    schema_dim = get_chunks_embedding_dim()
    if schema_dim is None:
        return None
    if schema_dim != active_dim:
        raise RuntimeError(
            "Embedding dimension mismatch: chunks.embedding is "
            f"vector({schema_dim}) but active embed dimension is {active_dim}. "
            "Apply the vector dimension migration and run reindex."
        )
    return schema_dim


def retrieve_similar_chunks(
    message: str,
    top_k: int = 4,
    embedding_fn: Callable[[str], list[float]] = get_embedding
) -> list[dict[str, Any]]:
    if engine.dialect.name != "postgresql":
        return []
    active_dim = get_active_embedding_dim()
    ensure_embedding_dimension_compatible()
    query_embedding = embedding_fn(message)
    if len(query_embedding) != active_dim:
        raise RuntimeError(
            f"Query embedding dimension {len(query_embedding)} does not match active "
            f"embed dimension {active_dim}. Reindex using the active embed provider/model."
        )
    vector_literal = _vector_literal(query_embedding)
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                """
                SELECT text, metadata
                FROM chunks
                ORDER BY embedding <=> (:embedding)::vector
                LIMIT :limit;
                """
            ),
            {"embedding": vector_literal, "limit": top_k}
        ).fetchall()
    return [{"text": row[0], "metadata": row[1]} for row in rows]


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
