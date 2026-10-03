"""Construyo el índice del modelo de embeddings configurado sin sobrescribir el activo.

Uso:
    python scripts/reindex_corpus.py

Leo los fragmentos utilizables desde la base (aprobados, vigentes y sin marcas), los indexo en
la colección de este modelo y dimensión, y recién al terminar la marco como activa. Si algo
falla, el índice anterior sigue activo.
"""
from __future__ import annotations

import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import Settings
from app.data.documents import PublicCorpusRepository
from app.db.engine import build_engine
from app.rag.ingestion import date_key
from app.rag.vector_store import IndexRegistry, build_vector_store


def reindex(settings: Settings) -> dict:
    engine = build_engine(settings.resolved_database_url())
    corpus = PublicCorpusRepository(engine)
    vector = build_vector_store(settings)
    rows = corpus.usable_chunks(datetime.now(tz=UTC).date())
    existing = set(vector.store.get(include=[])["ids"])  # type: ignore[attr-defined]
    pending = [r for r in rows if r["id"] not in existing]
    if pending:
        vector.store.add_texts(  # type: ignore[attr-defined]
            texts=[r["content"] for r in pending],
            ids=[r["id"] for r in pending],
            metadatas=[
                {
                    "doc_id": r["document_id"],
                    "chunk_id": r["id"],
                    "chunk_index": r["chunk_index"],
                    "title": r["title"],
                    "source": r["source"] or "",
                    "corpus": "public",
                    "valid_until": date_key(r["valid_until"]),
                }
                for r in pending
            ],
        )
    IndexRegistry(engine).ensure(vector.spec, chunk_count=len(rows))
    return {"model": vector.spec.model, "dimension": vector.spec.dimension, "collection": vector.spec.collection, "indexed": len(pending), "total": len(rows)}


if __name__ == "__main__":
    print(reindex(Settings()))
