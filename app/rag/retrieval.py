from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.core.config import Settings
from app.data.document_repo import DocumentRepository
from app.rag.vector_store import VectorStoreBundle


@dataclass(frozen=True)
class RetrievedChunk:
    content: str
    metadata: dict[str, Any]
    relevance: float


def retrieve(
    *,
    settings: Settings,
    doc_repo: DocumentRepository,
    vector: VectorStoreBundle,
    query: str,
    top_k: int | None = None,
) -> list[RetrievedChunk]:
    k = top_k or settings.rag_top_k
    candidates: list[RetrievedChunk] = []
    try:
        # Use similarity_search_with_score (returns raw distances) to avoid
        # the out-of-range warning from similarity_search_with_relevance_scores
        # when using hash embeddings whose cosine distances land outside [0, 1].
        results = vector.store.similarity_search_with_score(query, k=k)
        for doc, dist in results:
            rel = max(0.0, min(1.0, 1.0 / (1.0 + float(dist))))
            candidates.append(
                RetrievedChunk(content=doc.page_content, metadata=dict(doc.metadata), relevance=rel)
            )
    except Exception:
        candidates = []

    if candidates:
        strong = [c for c in candidates if c.relevance >= settings.rag_min_relevance]
        return strong or candidates[:1]

    keyword = doc_repo.keyword_search_chunks(query, limit=k)
    return [
        RetrievedChunk(
            content=r.content,
            metadata={"doc_id": r.doc_id, "chunk_id": r.chunk_id, "chunk_index": r.chunk_index},
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
