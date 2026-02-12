from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Iterable, List

from pypdf import PdfReader
from sqlalchemy import text

from . import db
from .embed_dimension import get_active_embedding_dim
from .embeddings import get_embedding


def chunk_text(text_value: str, chunk_size: int = 1500, overlap: int = 200) -> List[str]:
    if chunk_size <= overlap:
        raise ValueError("chunk_size must be larger than overlap")
    chunks = []
    start = 0
    text_length = len(text_value)
    while start < text_length:
        end = min(start + chunk_size, text_length)
        chunk = text_value[start:end].strip()
        if chunk:
            chunks.append(chunk)
        start += chunk_size - overlap
    return chunks


def _vector_literal(values: List[float]) -> str:
    return "[" + ",".join(f"{value:.6f}" for value in values) + "]"


def _read_pdf(path: Path) -> str:
    reader = PdfReader(str(path))
    parts = []
    for page in reader.pages:
        parts.append(page.extract_text() or "")
    return "\n".join(parts)


def _read_txt(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="ignore")


def _iter_paths(root: Path) -> Iterable[Path]:
    for path in root.rglob("*"):
        if path.is_file() and path.suffix.lower() in {".txt", ".pdf"}:
            yield path


def ingest_paths(
    root: Path,
    reset: bool = False,
    embed_fn=get_embedding
) -> int:
    db.init_db()
    active_dim = get_active_embedding_dim()
    db.ensure_embedding_dimension_compatible()
    inserted_chunks = 0
    with db.engine.begin() as conn:
        if reset:
            conn.execute(text("DELETE FROM chunks;"))
            conn.execute(text("DELETE FROM documents;"))

        for path in _iter_paths(root):
            content = _read_pdf(path) if path.suffix.lower() == ".pdf" else _read_txt(path)
            chunks = chunk_text(content)
            if not chunks:
                continue
            source_id = str(path.relative_to(root))
            title = path.stem
            doc_type = path.suffix.lower().lstrip(".")
            tags = json.dumps([])
            result = conn.execute(
                text(
                    """
                    INSERT INTO documents (source_id, title, url, year, doc_type, tags)
                    VALUES (:source_id, :title, :url, :year, :doc_type, :tags)
                    ON CONFLICT (source_id) DO UPDATE SET title = EXCLUDED.title
                    RETURNING id;
                    """
                ),
                {
                    "source_id": source_id,
                    "title": title,
                    "url": None,
                    "year": None,
                    "doc_type": doc_type,
                    "tags": tags
                }
            )
            document_id = result.scalar_one()
            for index, chunk in enumerate(chunks):
                embedding = embed_fn(chunk)
                if len(embedding) != active_dim:
                    raise RuntimeError(
                        f"Embedding dimension {len(embedding)} does not match active "
                        f"dimension {active_dim}. Update provider config and reindex."
                    )
                metadata = json.dumps({"source_id": source_id})
                conn.execute(
                    text(
                        """
                        INSERT INTO chunks (document_id, chunk_index, text, metadata, embedding)
                        VALUES (:document_id, :chunk_index, :text, (:metadata)::jsonb, (:embedding)::vector)
                        ON CONFLICT (document_id, chunk_index) DO NOTHING;
                        """
                    ),
                    {
                        "document_id": document_id,
                        "chunk_index": index,
                        "text": chunk,
                        "metadata": metadata,
                        "embedding": _vector_literal(embedding)
                    }
                )
                inserted_chunks += 1
    return inserted_chunks


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--path", required=True)
    parser.add_argument("--reset", action="store_true")
    args = parser.parse_args()

    root = Path(args.path)
    if not root.exists():
        raise SystemExit(f"Path not found: {root}")

    count = ingest_paths(root, reset=args.reset)
    print(f"Inserted {count} chunks.")


if __name__ == "__main__":
    main()
