from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from app.core.config import Settings
from app.data.documents import Provenance, PublicCorpusRepository, sha256_text
from app.rag.safety import injection_reason
from app.rag.vector_store import IndexRegistry, VectorStoreBundle


@dataclass(frozen=True)
class IngestionResult:
    doc_id: str
    chunks_indexed: int
    chunks_flagged: int = 0


def split_fixed_window(text: str, size: int, overlap: int) -> list[str]:
    """Divido el texto en ventanas fijas con solapamiento.

    Avanzo siempre al menos un carácter por iteración y corto al alcanzar el
    final del texto, de modo que la función termina para cualquier entrada.
    """
    if size < 1:
        raise ValueError("size must be at least 1")
    overlap = max(0, min(overlap, size - 1))
    step = size - overlap
    chunks: list[str] = []
    start = 0
    length = len(text)
    while start < length:
        end = min(length, start + size)
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= length:
            break
        start += step
    return chunks


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
        # Uso ventanas fijas cuando el divisor principal no está disponible.
        return split_fixed_window(
            text,
            size=max(200, settings.rag_chunk_size),
            overlap=settings.rag_chunk_overlap,
        )


def date_key(value: date) -> int:
    """Represento fechas como entero AAAAMMDD para poder filtrarlas en el índice vectorial."""
    return value.year * 10000 + value.month * 100 + value.day


class IngestionRejected(ValueError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def ingest_public_document(
    *,
    settings: Settings,
    corpus: PublicCorpusRepository,
    vector: VectorStoreBundle,
    title: str,
    content: str,
    provenance: Provenance,
    registry: IndexRegistry | None = None,
) -> IngestionResult:
    """Ingiero un documento curado con procedencia y vigencia.

    Registro el estado en `ingestion_jobs`. Si algo falla a mitad de camino, el reintento retoma
    desde donde quedó: no duplica documento, fragmentos ni embeddings. Los fragmentos con
    instrucciones sospechosas quedan guardados para auditoría, pero no se indexan.
    """
    if len(content.encode("utf-8")) > settings.ingest_max_bytes:
        raise IngestionRejected("document_too_large")
    if registry is not None and not registry.matches(vector.spec):
        raise RuntimeError("The active vector index uses another embedding model. Reindex before ingesting.")
    pieces = chunk_text(settings, content)
    if len(pieces) > settings.ingest_max_chunks:
        raise IngestionRejected("too_many_chunks")
    sha = sha256_text(content)
    job = corpus.start_job(sha)
    if job["status"] == "completed":
        return IngestionResult(doc_id=job["document_id"], chunks_indexed=0, chunks_flagged=job["chunks_flagged"])
    doc = corpus.create_document(title=title, content=content, provenance=provenance)
    records = corpus.chunks_for(doc.doc_id)
    if not records:
        records = corpus.add_chunks(doc.doc_id, [(piece, injection_reason(piece)) for piece in pieces])
    indexable = [r for r in records if r.flagged_reason is None]
    flagged = len(records) - len(indexable)
    corpus.update_job(sha, document_id=doc.doc_id, status="embedding", chunks_total=len(records), chunks_flagged=flagged)
    try:
        added = vector.store.add([(r.chunk_id, r.content) for r in indexable])
    except Exception as exc:
        corpus.update_job(sha, status="failed", error_code=type(exc).__name__[:40])
        raise RuntimeError("Failed to embed document chunks; retry to resume the ingestion.") from exc
    corpus.update_job(sha, status="completed", chunks_embedded=len(indexable), error_code=None)
    if registry is not None:
        registry.ensure(vector.spec, chunk_count=len(corpus.usable_chunks(date.today())))
    return IngestionResult(doc_id=doc.doc_id, chunks_indexed=added, chunks_flagged=flagged)
