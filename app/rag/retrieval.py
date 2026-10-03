from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.core.config import Settings
from app.data.documents import PUBLIC_CORPUS, PublicCorpusRepository
from app.rag.vector_store import VectorStoreBundle


@dataclass(frozen=True)
class RetrievedChunk:
    content: str
    metadata: dict[str, Any]
    relevance: float


def retrieve(
    *,
    settings: Settings,
    corpus: PublicCorpusRepository,
    vector: VectorStoreBundle,
    query: str,
    top_k: int | None = None,
) -> list[RetrievedChunk]:
    """Recupero solo del corpus público. El filtro va dentro de la búsqueda vectorial y de la SQL;
    no recupero contenido ajeno para filtrarlo después."""
    k = top_k or settings.rag_top_k
    candidates: list[RetrievedChunk] = []
    try:
        # Recupero distancias crudas para evitar advertencias de normalización.
        # Mantengo esta transformación como heurística pendiente de evaluación.
        results = vector.store.similarity_search_with_score(query, k=k, filter={"corpus": PUBLIC_CORPUS})
        for doc, dist in results:
            if doc.metadata.get("corpus") != PUBLIC_CORPUS:
                continue
            rel = max(0.0, min(1.0, 1.0 / (1.0 + float(dist))))
            candidates.append(
                RetrievedChunk(content=doc.page_content, metadata=dict(doc.metadata), relevance=rel)
            )
    except Exception:
        candidates = []

    if candidates:
        strong = [c for c in candidates if c.relevance >= settings.rag_min_relevance]
        return strong or candidates[:1]

    keyword = corpus.keyword_search_chunks(query, limit=k)
    return [
        RetrievedChunk(
            content=r["content"],
            metadata={
                "doc_id": r["document_id"],
                "chunk_id": r["id"],
                "chunk_index": r["chunk_index"],
                "title": r["title"],
                "source": r["source"],
                "corpus": PUBLIC_CORPUS,
            },
            relevance=0.0,
        )
        for r in keyword
    ]


def build_context(chunks: list[RetrievedChunk], max_chars: int = 6000) -> tuple[str, list[dict[str, Any]]]:
    parts: list[str] = []
    citations: list[dict[str, Any]] = []
    used = 0
    for c in chunks:
        meta = c.metadata
        cite = {
            "doc_id": meta.get("doc_id"),
            "chunk_id": meta.get("chunk_id"),
            "title": meta.get("title"),
            "source": meta.get("source"),
        }
        block = f"Source: {cite.get('title') or cite['doc_id']} | {cite.get('source') or 'n/a'}\n{c.content}".strip()
        if used + len(block) + 2 > max_chars:
            break
        parts.append(block)
        citations.append(cite)
        used += len(block) + 2
    return "\n\n---\n\n".join(parts), citations
