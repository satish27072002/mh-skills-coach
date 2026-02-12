from __future__ import annotations

import argparse
import logging

from sqlalchemy import text

from .. import db
from ..embed_dimension import get_active_embedding_dim
from ..embeddings import get_embedding


logger = logging.getLogger(__name__)


def _vector_literal(values: list[float]) -> str:
    return "[" + ",".join(f"{value:.6f}" for value in values) + "]"


def reindex_embeddings(log_every: int = 25) -> dict[str, int]:
    db.init_db()
    active_dim = get_active_embedding_dim()
    db.ensure_embedding_dimension_compatible()
    with db.engine.begin() as conn:
        rows = conn.execute(
            text("SELECT id, text FROM chunks ORDER BY id;")
        ).fetchall()
        total = len(rows)
        if total == 0:
            logger.info("Reindex complete. No chunks found.")
            return {"total_chunks": 0, "updated_chunks": 0}

        conn.execute(text("UPDATE chunks SET embedding = NULL;"))
        updated = 0
        logger.info("Starting reindex for %s chunks using embed_dim=%s", total, active_dim)
        for chunk_id, chunk_text in rows:
            embedding = get_embedding(chunk_text)
            if len(embedding) != active_dim:
                raise RuntimeError(
                    f"Embedding dimension {len(embedding)} does not match active dimension {active_dim}."
                )
            conn.execute(
                text(
                    """
                    UPDATE chunks
                    SET embedding = (:embedding)::vector
                    WHERE id = :id;
                    """
                ),
                {"id": int(chunk_id), "embedding": _vector_literal(embedding)}
            )
            updated += 1
            if log_every > 0 and updated % log_every == 0:
                logger.info("Reindex progress: %s/%s chunks", updated, total)
        logger.info("Reindex complete. Updated %s/%s chunks.", updated, total)
        return {"total_chunks": total, "updated_chunks": updated}


def main() -> None:
    parser = argparse.ArgumentParser(description="Re-embed all chunk vectors with active provider.")
    parser.add_argument("--log-every", type=int, default=25)
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    result = reindex_embeddings(log_every=args.log_every)
    print(
        "Reindex complete: "
        f"{result['updated_chunks']}/{result['total_chunks']} chunks updated."
    )


if __name__ == "__main__":
    main()
