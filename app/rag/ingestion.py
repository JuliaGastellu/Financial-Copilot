from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from app.core.config import Settings
from app.data.documents import PUBLIC_CORPUS, ChunkRecord, Provenance, PublicCorpusRepository
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


def chunk_metadata(record: ChunkRecord, title: str, provenance: Provenance) -> dict:
    return {
        "doc_id": record.doc_id,
        "chunk_id": record.chunk_id,
        "chunk_index": record.chunk_index,
        "title": title,
        "source": provenance.source,
        "sha256": record.sha256,
        "corpus": PUBLIC_CORPUS,
        "valid_until": date_key(provenance.valid_until),
    }


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
    """Ingiero un documento curado con procedencia y vigencia. Repetir la ingesta no duplica contenido.

    Guardo los fragmentos con instrucciones sospechosas para auditoría, pero no los indexo.
    """
    if registry is not None and not registry.matches(vector.spec):
        raise RuntimeError("The active vector index uses another embedding model. Reindex before ingesting.")
    doc = corpus.create_document(title=title, content=content, provenance=provenance)
    if not doc.created:
        return IngestionResult(doc_id=doc.doc_id, chunks_indexed=0)
    pieces = chunk_text(settings, content)
    records = corpus.add_chunks(doc.doc_id, [(piece, injection_reason(piece)) for piece in pieces])
    indexable = [r for r in records if r.flagged_reason is None]
    if indexable:
        try:
            vector.store.add_texts(
                texts=[r.content for r in indexable],
                metadatas=[chunk_metadata(r, title, provenance) for r in indexable],
                ids=[r.chunk_id for r in indexable],
            )
        except Exception as exc:
            # Revierto el documento para que un reintento vuelva a indexarlo.
            corpus.delete_document(doc.doc_id)
            raise RuntimeError("Failed to index document chunks in the vector store.") from exc
    if registry is not None:
        registry.ensure(vector.spec, chunk_count=len(corpus.usable_chunks(date.today())))
    return IngestionResult(doc_id=doc.doc_id, chunks_indexed=len(indexable), chunks_flagged=len(records) - len(indexable))
