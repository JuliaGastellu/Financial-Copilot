"""Corpus público curado. No guardo documentos de personas usuarias en esta etapa.

Solo recupero fragmentos de documentos aprobados, vigentes y sin marcas de instrucciones
sospechosas. Esos filtros van en la consulta SQL, no después.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import date
from typing import Any, Iterable

from sqlalchemy import Engine, and_, delete, insert, select

from app.data.accounts import new_id, utc_now
from app.db.schema import chunks, documents

PUBLIC_CORPUS = "public"


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class Provenance:
    publisher: str
    source: str
    published_on: date
    reviewed_on: date
    valid_until: date

    def __post_init__(self) -> None:
        if not self.publisher.strip() or not self.source.strip():
            raise ValueError("Publisher and source are required.")
        if self.valid_until < self.reviewed_on:
            raise ValueError("valid_until must be on or after reviewed_on.")


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
    flagged_reason: str | None = None


def _usable(today: date) -> Any:
    return and_(
        chunks.c.corpus == PUBLIC_CORPUS,
        documents.c.corpus == PUBLIC_CORPUS,
        documents.c.review_status == "approved",
        documents.c.valid_until >= today,
        chunks.c.flagged_reason.is_(None),
    )


_CHUNK_COLUMNS = (
    chunks.c.id,
    chunks.c.document_id,
    chunks.c.chunk_index,
    chunks.c.content,
    documents.c.title,
    documents.c.source,
    documents.c.publisher,
    documents.c.published_on,
    documents.c.valid_until,
)


@dataclass(frozen=True)
class PublicCorpusRepository:
    engine: Engine

    def create_document(self, *, title: str, content: str, provenance: Provenance) -> DocumentRecord:
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
                    source=provenance.source,
                    content=content,
                    sha256=content_hash,
                    created_at=utc_now(),
                    publisher=provenance.publisher,
                    published_on=provenance.published_on,
                    reviewed_on=provenance.reviewed_on,
                    valid_until=provenance.valid_until,
                    review_status="approved",
                )
            )
        return DocumentRecord(doc_id, title, provenance.source, content_hash, created=True)

    def add_chunks(self, doc_id: str, items: Iterable[tuple[str, str | None]]) -> list[ChunkRecord]:
        records = [
            ChunkRecord(chunk_id=new_id(), doc_id=doc_id, chunk_index=i, content=text, sha256=sha256_text(text), flagged_reason=flag)
            for i, (text, flag) in enumerate(items)
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
                            "flagged_reason": r.flagged_reason,
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
            return [ChunkRecord(r["id"], r["document_id"], r["chunk_index"], r["content"], r["sha256"], r["flagged_reason"]) for r in rows]

    def usable_chunks(self, today: date) -> list[dict[str, Any]]:
        """Fragmentos que pueden indexarse y recuperarse hoy (para reindexar)."""
        with self.engine.connect() as conn:
            rows = conn.execute(
                select(*_CHUNK_COLUMNS).join(documents, documents.c.id == chunks.c.document_id).where(_usable(today))
            ).mappings()
            return [dict(r) for r in rows]

    def usable_by_ids(self, ids: list[str], today: date) -> dict[str, dict[str, Any]]:
        if not ids:
            return {}
        with self.engine.connect() as conn:
            rows = conn.execute(
                select(*_CHUNK_COLUMNS)
                .join(documents, documents.c.id == chunks.c.document_id)
                .where(_usable(today), chunks.c.id.in_(ids))
            ).mappings()
            return {r["id"]: dict(r) for r in rows}
