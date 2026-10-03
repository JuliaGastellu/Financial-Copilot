"""Corpus público curado. No guardo documentos de personas usuarias en esta etapa."""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any, Iterable

from sqlalchemy import Engine, delete, insert, select

from app.data.accounts import new_id, utc_now
from app.db.schema import chunks, documents

PUBLIC_CORPUS = "public"


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class DocumentRecord:
    doc_id: str
    title: str
    source: str | None
    sha256: str
    created: bool


@dataclass(frozen=True)
class ChunkRecord:
    chunk_id: str
    doc_id: str
    chunk_index: int
    content: str
    sha256: str


@dataclass(frozen=True)
class PublicCorpusRepository:
    engine: Engine

    def create_document(self, *, title: str, source: str | None, content: str) -> DocumentRecord:
        """Creo el documento o devuelvo el existente con el mismo contenido (ingesta idempotente)."""
        content_hash = sha256_text(content)
        with self.engine.begin() as conn:
            row = conn.execute(
                select(documents.c.id, documents.c.title, documents.c.source).where(
                    documents.c.corpus == PUBLIC_CORPUS, documents.c.sha256 == content_hash
                )
            ).first()
            if row is not None:
                return DocumentRecord(row.id, row.title, row.source, content_hash, created=False)
            doc_id = new_id()
            conn.execute(
                insert(documents).values(
                    id=doc_id,
                    corpus=PUBLIC_CORPUS,
                    title=title,
                    source=source,
                    content=content,
                    sha256=content_hash,
                    created_at=utc_now(),
                )
            )
        return DocumentRecord(doc_id, title, source, content_hash, created=True)

    def add_chunks(self, doc_id: str, texts: Iterable[str]) -> list[ChunkRecord]:
        records = [
            ChunkRecord(chunk_id=new_id(), doc_id=doc_id, chunk_index=i, content=t, sha256=sha256_text(t))
            for i, t in enumerate(texts)
        ]
        if records:
            with self.engine.begin() as conn:
                conn.execute(
                    insert(chunks),
                    [
                        {
                            "id": r.chunk_id,
                            "document_id": r.doc_id,
                            "corpus": PUBLIC_CORPUS,
                            "chunk_index": r.chunk_index,
                            "content": r.content,
                            "sha256": r.sha256,
                        }
                        for r in records
                    ],
                )
        return records

    def delete_document(self, doc_id: str) -> None:
        with self.engine.begin() as conn:
            conn.execute(delete(chunks).where(chunks.c.document_id == doc_id))
            conn.execute(delete(documents).where(documents.c.id == doc_id))

    def chunks_for(self, doc_id: str) -> list[ChunkRecord]:
        with self.engine.connect() as conn:
            rows = conn.execute(
                select(chunks).where(chunks.c.document_id == doc_id, chunks.c.corpus == PUBLIC_CORPUS).order_by(chunks.c.chunk_index)
            ).mappings()
            return [ChunkRecord(r["id"], r["document_id"], r["chunk_index"], r["content"], r["sha256"]) for r in rows]

    def keyword_search_chunks(self, query: str, limit: int = 6) -> list[dict[str, Any]]:
        """Búsqueda alternativa en SQL. El filtro de corpus va en la consulta, no después."""
        pattern = f"%{query.strip()}%"
        with self.engine.connect() as conn:
            rows = conn.execute(
                select(chunks.c.id, chunks.c.document_id, chunks.c.chunk_index, chunks.c.content, documents.c.title, documents.c.source)
                .join(documents, documents.c.id == chunks.c.document_id)
                .where(chunks.c.corpus == PUBLIC_CORPUS, documents.c.corpus == PUBLIC_CORPUS, chunks.c.content.like(pattern))
                .limit(limit)
            ).mappings()
            return [dict(r) for r in rows]
