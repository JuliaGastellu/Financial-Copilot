from __future__ import annotations

from dataclasses import dataclass

from app.core.config import Settings
from app.data.document_repo import DocumentRepository
from app.rag.vector_store import VectorStoreBundle


@dataclass(frozen=True)
class IngestionResult:
    doc_id: str
    chunks_indexed: int


def chunk_text(settings: Settings, text: str) -> list[str]:
    try:
        from langchain_text_splitters import RecursiveCharacterTextSplitter

        splitter = RecursiveCharacterTextSplitter(
            chunk_size=settings.rag_chunk_size,
            chunk_overlap=settings.rag_chunk_overlap,
            separators=["\n\n", "\n", ". ", " ", ""],
        )
        return splitter.split_text(text)
    except Exception:
        chunks: list[str] = []
        size = max(200, settings.rag_chunk_size)
        overlap = max(0, min(settings.rag_chunk_overlap, size - 1))
        pos = 0
        while pos < len(text):
            end = min(len(text), pos + size)
            chunk = text[pos:end].strip()
            if chunk:
                chunks.append(chunk)
            pos = end - overlap
            if pos < 0:
                pos = end
        return chunks


def ingest_document(
    *,
    settings: Settings,
    doc_repo: DocumentRepository,
    vector: VectorStoreBundle,
    title: str,
    source: str | None,
    content: str,
) -> IngestionResult:
    doc = doc_repo.create_document(title=title, source=source, content=content)
    chunks = chunk_text(settings, content)
    chunk_records = doc_repo.add_chunks(doc.doc_id, chunks)
    texts = [c.content for c in chunk_records]
    ids = [c.chunk_id for c in chunk_records]
    metadatas = [
        {
            "doc_id": c.doc_id,
            "chunk_id": c.chunk_id,
            "chunk_index": c.chunk_index,
            "title": title,
            "source": source,
            "sha256": c.sha256,
        }
        for c in chunk_records
    ]

    try:
        vector.store.add_texts(texts=texts, metadatas=metadatas, ids=ids)
    except Exception as exc:
        raise RuntimeError("Failed to index document chunks in the vector store.") from exc
    return IngestionResult(doc_id=doc.doc_id, chunks_indexed=len(chunk_records))
