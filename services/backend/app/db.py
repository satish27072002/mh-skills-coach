from typing import Any, Callable, Iterable

from sqlalchemy import create_engine, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from .config import settings
from .embed_dimension import get_active_embedding_dim
from .embeddings import get_embedding


class Base(DeclarativeBase):
    pass


def _make_engine(database_url: str):
    if database_url.startswith("postgresql://"):
        database_url = "postgresql+psycopg://" + database_url[len("postgresql://"):]
    if database_url.startswith("postgres://"):
        database_url = "postgresql+psycopg://" + database_url[len("postgres://"):]
    return create_engine(database_url, pool_pre_ping=True)


engine = _make_engine(settings.database_url)
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)


def init_db() -> None:
    from . import models

    if engine.dialect.name == "sqlite":
        with engine.begin() as conn:
            has_users = conn.execute(
                text(
                    """
                    SELECT name
                    FROM sqlite_master
                    WHERE type='table' AND name='users';
                    """
                )
            ).fetchone()
            if has_users:
                columns = conn.execute(text("PRAGMA table_info(users);")).fetchall()
                column_names = {str(row[1]) for row in columns}
                id_decl = str(columns[0][2]).upper() if columns else ""
                legacy_layout = "google_sub" not in column_names or "INT" in id_decl
                if legacy_layout:
                    conn.execute(text("DROP TABLE IF EXISTS users;"))

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
            conn.execute(
                text(
                    """
                    CREATE EXTENSION IF NOT EXISTS pgcrypto;
                    """
                )
            )
            conn.execute(
                text(
                    """
                    DO $$
                    BEGIN
                        IF to_regclass('public.users') IS NULL THEN
                            CREATE TABLE public.users (
                                id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
                                google_sub text NOT NULL UNIQUE,
                                email text NULL,
                                name text NULL,
                                is_premium boolean NOT NULL DEFAULT false,
                                stripe_customer_id text NULL,
                                premium_until timestamptz NULL,
                                created_at timestamptz NOT NULL DEFAULT now(),
                                updated_at timestamptz NOT NULL DEFAULT now()
                            );
                        ELSE
                            IF EXISTS (
                                SELECT 1
                                FROM information_schema.columns
                                WHERE table_schema = 'public'
                                  AND table_name = 'users'
                                  AND column_name = 'id'
                                  AND data_type <> 'uuid'
                            ) THEN
                                ALTER TABLE public.users ADD COLUMN IF NOT EXISTS id_uuid uuid;
                                UPDATE public.users
                                SET id_uuid = COALESCE(id_uuid, gen_random_uuid());
                                ALTER TABLE public.users DROP CONSTRAINT IF EXISTS users_pkey;
                                ALTER TABLE public.users DROP COLUMN IF EXISTS id;
                                ALTER TABLE public.users RENAME COLUMN id_uuid TO id;
                                ALTER TABLE public.users ADD PRIMARY KEY (id);
                            END IF;

                            ALTER TABLE public.users ADD COLUMN IF NOT EXISTS google_sub text;
                            ALTER TABLE public.users ADD COLUMN IF NOT EXISTS email text;
                            ALTER TABLE public.users ADD COLUMN IF NOT EXISTS name text;
                            ALTER TABLE public.users ADD COLUMN IF NOT EXISTS is_premium boolean NOT NULL DEFAULT false;
                            ALTER TABLE public.users ADD COLUMN IF NOT EXISTS stripe_customer_id text;
                            ALTER TABLE public.users ADD COLUMN IF NOT EXISTS premium_until timestamptz;
                            ALTER TABLE public.users ADD COLUMN IF NOT EXISTS created_at timestamptz NOT NULL DEFAULT now();
                            ALTER TABLE public.users ADD COLUMN IF NOT EXISTS updated_at timestamptz NOT NULL DEFAULT now();

                            UPDATE public.users
                            SET google_sub = COALESCE(NULLIF(google_sub, ''), 'legacy-' || id::text)
                            WHERE google_sub IS NULL OR google_sub = '';

                            ALTER TABLE public.users ALTER COLUMN google_sub SET NOT NULL;
                        END IF;
                    END $$;
                    """
                )
            )
            conn.execute(
                text(
                    """
                    CREATE UNIQUE INDEX IF NOT EXISTS users_google_sub_idx
                    ON public.users (google_sub);
                    """
                )
            )
            conn.execute(
                text(
                    """
                    CREATE UNIQUE INDEX IF NOT EXISTS users_email_idx
                    ON public.users (email)
                    WHERE email IS NOT NULL;
                    """
                )
            )
            conn.execute(
                text(
                    """
                    CREATE UNIQUE INDEX IF NOT EXISTS users_stripe_customer_id_idx
                    ON public.users (stripe_customer_id)
                    WHERE stripe_customer_id IS NOT NULL;
                    """
                )
            )
            conn.execute(
                text(
                    """
                    CREATE OR REPLACE FUNCTION public.set_users_updated_at()
                    RETURNS trigger
                    LANGUAGE plpgsql
                    AS $$
                    BEGIN
                        NEW.updated_at = now();
                        RETURN NEW;
                    END;
                    $$;
                    """
                )
            )
            conn.execute(
                text(
                    """
                    DROP TRIGGER IF EXISTS users_set_updated_at ON public.users;
                    CREATE TRIGGER users_set_updated_at
                    BEFORE UPDATE ON public.users
                    FOR EACH ROW
                    EXECUTE FUNCTION public.set_users_updated_at();
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
    return typmod


def ensure_embedding_dimension_compatible() -> int | None:
    if engine.dialect.name != "postgresql":
        return None
    active_dim = get_active_embedding_dim()
    schema_typmod = get_chunks_embedding_dim()
    if schema_typmod is None:
        return None
    if schema_typmod not in {active_dim, active_dim + 4}:
        schema_dim = schema_typmod - 4 if schema_typmod > 4 else schema_typmod
        raise RuntimeError(
            "Embedding dimension mismatch: chunks.embedding is "
            f"vector({schema_dim}) but active embed dimension is {active_dim}. "
            "Apply the vector dimension migration and run reindex."
        )
    return active_dim


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
