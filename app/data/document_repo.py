from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass
from typing import Any, Iterable

from app.data.sqlite import SqliteDb, query_all, query_one, utc_now_iso


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class DocumentRecord:
    doc_id: str
    title: str
    source: str | None
    sha256: str


@dataclass(frozen=True)
class ChunkRecord:
    chunk_id: str
    doc_id: str
    chunk_index: int
    content: str
    sha256: str


@dataclass(frozen=True)
class DocumentRepository:
    db: SqliteDb

    def create_document(self, *, title: str, source: str | None, content: str) -> DocumentRecord:
        doc_id = str(uuid.uuid4())
        content_hash = sha256_text(content)
        created_at = utc_now_iso()
        with self.db.connect() as conn:
            conn.execute(
                "INSERT INTO documents (doc_id, title, source, content, sha256, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (doc_id, title, source, content, content_hash, created_at),
            )
        return DocumentRecord(doc_id=doc_id, title=title, source=source, sha256=content_hash)

    def add_chunks(self, doc_id: str, chunks: Iterable[str]) -> list[ChunkRecord]:
        records: list[ChunkRecord] = []
        with self.db.connect() as conn:
            for idx, chunk_text in enumerate(chunks):
                chunk_id = str(uuid.uuid4())
                chunk_hash = sha256_text(chunk_text)
                conn.execute(
                    "INSERT INTO chunks (chunk_id, doc_id, chunk_index, content, sha256) VALUES (?, ?, ?, ?, ?)",
                    (chunk_id, doc_id, idx, chunk_text, chunk_hash),
                )
                records.append(
                    ChunkRecord(
                        chunk_id=chunk_id,
                        doc_id=doc_id,
                        chunk_index=idx,
                        content=chunk_text,
                        sha256=chunk_hash,
                    )
                )
        return records

    def get_document_content(self, doc_id: str) -> dict[str, Any] | None:
        with self.db.connect() as conn:
            row = query_one(
                conn,
                "SELECT doc_id, title, source, content, sha256, created_at FROM documents WHERE doc_id = ?",
                (doc_id,),
            )
            if row is None:
                return None
            return dict(row)

    def list_documents(self, limit: int = 50) -> list[dict[str, Any]]:
        with self.db.connect() as conn:
            rows = query_all(
                conn,
                "SELECT doc_id, title, source, sha256, created_at FROM documents ORDER BY created_at DESC LIMIT ?",
                (limit,),
            )
            return [dict(r) for r in rows]

    def keyword_search_chunks(self, query: str, limit: int = 6) -> list[ChunkRecord]:
        pattern = f"%{query.strip()}%"
        with self.db.connect() as conn:
            rows = query_all(
                conn,
                "SELECT chunk_id, doc_id, chunk_index, content, sha256 FROM chunks WHERE content LIKE ? LIMIT ?",
                (pattern, limit),
            )
            return [
                ChunkRecord(
                    chunk_id=r["chunk_id"],
                    doc_id=r["doc_id"],
                    chunk_index=r["chunk_index"],
                    content=r["content"],
                    sha256=r["sha256"],
                )
                for r in rows
            ]

