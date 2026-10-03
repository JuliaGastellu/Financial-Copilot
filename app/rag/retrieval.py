"""Recuperación sobre el corpus público con umbral de relevancia y abstención.

No devuelvo candidatos por debajo del umbral: si no hay evidencia suficiente, la respuesta
es una abstención. Los filtros de corpus, aprobación y vigencia van dentro de la búsqueda.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any

from app.core.config import Settings
from app.data.documents import PUBLIC_CORPUS, PublicCorpusRepository
from app.rag.embeddings import normalize_tokens
from app.rag.ingestion import date_key
from app.rag.vector_store import IndexRegistry, VectorStoreBundle


@dataclass(frozen=True)
class RetrievedChunk:
    content: str
    metadata: dict[str, Any]
    relevance: float


@dataclass(frozen=True)
class Retrieval:
    chunks: list[RetrievedChunk]
    method: str
    considered: int = 0
    below_threshold: int = 0
    notes: list[str] = field(default_factory=list)


def _meta(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "doc_id": row["document_id"],
        "chunk_id": row["id"],
        "chunk_index": row["chunk_index"],
        "title": row["title"],
        "source": row["source"],
        "publisher": row["publisher"],
        "published_on": row["published_on"].isoformat() if row["published_on"] else None,
        "valid_until": row["valid_until"].isoformat() if row["valid_until"] else None,
        "corpus": PUBLIC_CORPUS,
    }


def keyword_overlap(query_terms: set[str], text: str) -> float:
    if not query_terms:
        return 0.0
    return len(query_terms & set(normalize_tokens(text))) / len(query_terms)


def retrieve(
    *,
    settings: Settings,
    corpus: PublicCorpusRepository,
    vector: VectorStoreBundle,
    query: str,
    top_k: int | None = None,
    today: date | None = None,
    registry: IndexRegistry | None = None,
) -> Retrieval:
    today = today or date.today()
    k = top_k or settings.rag_top_k
    notes: list[str] = []
    if registry is not None and not registry.matches(vector.spec):
        notes.append("index_model_mismatch")
    else:
        try:
            results = vector.store.similarity_search_with_score(
                query,
                k=k,
                filter={"$and": [{"corpus": PUBLIC_CORPUS}, {"valid_until": {"$gte": date_key(today)}}]},
            )
            ids = [doc.metadata.get("chunk_id") for doc, _ in results]
            # Confirmo en SQL que cada fragmento sigue aprobado, vigente y sin marcas.
            usable = corpus.usable_by_ids([i for i in ids if i], today)
            strong: list[RetrievedChunk] = []
            below = 0
            for doc, distance in results:
                row = usable.get(doc.metadata.get("chunk_id"))
                if row is None:
                    continue
                relevance = max(0.0, 1.0 - float(distance))  # distancia coseno
                if relevance < settings.rag_min_relevance:
                    below += 1
                    continue
                strong.append(RetrievedChunk(content=row["content"], metadata=_meta(row), relevance=round(relevance, 4)))
            return Retrieval(chunks=strong, method="vector", considered=len(results), below_threshold=below, notes=notes)
        except Exception:
            notes.append("vector_search_unavailable")

    # Alternativa sin índice: coincidencia de términos sobre fragmentos utilizables, con su propio umbral.
    terms = set(normalize_tokens(query))
    scored = []
    for row in corpus.usable_chunks(today):
        score = keyword_overlap(terms, row["content"])
        if score >= settings.rag_min_keyword_overlap:
            scored.append(RetrievedChunk(content=row["content"], metadata=_meta(row), relevance=round(score, 4)))
    scored.sort(key=lambda c: c.relevance, reverse=True)
    return Retrieval(chunks=scored[:k], method="keyword", considered=len(scored), notes=notes)
