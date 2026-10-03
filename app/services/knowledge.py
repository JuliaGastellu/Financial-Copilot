"""Preguntas educativas sobre el corpus público. No uso el perfil ni datos de la cuenta."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any

from app.core.config import Settings
from app.data.documents import PublicCorpusRepository
from app.rag.answer import TermStats, compose_answer
from app.rag.retrieval import retrieve
from app.rag.vector_store import IndexRegistry, VectorStoreBundle


ABSTENTION_TEXT = {
    "no_evidence": "No encontré material vigente del corpus que responda esta pregunta, así que no respondo sin evidencia.",
    "out_of_scope": "Esta herramienta no recomienda instrumentos ni inversiones personales. Puedo responder preguntas educativas generales.",
}


@dataclass(frozen=True)
class KnowledgeService:
    settings: Settings
    corpus: PublicCorpusRepository
    vector: VectorStoreBundle
    registry: IndexRegistry

    def answer(self, query: str, top_k: int | None, today: date | None = None) -> dict[str, Any]:
        today = today or datetime.now(tz=UTC).date()
        retrieval = retrieve(
            settings=self.settings, corpus=self.corpus, vector=self.vector, query=query, top_k=top_k, today=today, registry=self.registry
        )
        stats = TermStats.from_texts(row["content"] for row in self.corpus.usable_chunks(today))
        result = compose_answer(query, retrieval.chunks, stats)
        claims = [{"text": c.text, "citations": [c.citation]} for c in result.claims]
        unique: dict[str, dict] = {}
        for c in result.claims:
            unique.setdefault(c.citation["chunk_id"], c.citation)
        return {
            "status": result.status,
            "abstention_reason": result.abstention_reason,
            "answer": " ".join(c.text for c in result.claims) if result.claims else ABSTENTION_TEXT[result.abstention_reason or "no_evidence"],
            "claims": claims,
            "citations": list(unique.values()),
            "retrieval": {"method": retrieval.method, "considered": retrieval.considered, "below_threshold": retrieval.below_threshold},
        }
