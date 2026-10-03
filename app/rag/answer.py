"""Respuestas educativas extractivas con una cita por afirmación.

Cada afirmación es una oración literal de un fragmento recuperado del corpus público y lleva
la cita de ese fragmento. No genero texto nuevo, así que toda afirmación está respaldada por
construcción.

La recuperación vectorial solo propone candidatos. La decisión de responder es léxica: pondero
los términos de la pregunta por su rareza en el corpus (IDF) y exijo que las oraciones elegidas
cubran la mayor parte de ese peso. Un término que no aparece en el corpus pesa al máximo, así
que una pregunta sobre un tema ausente termina en abstención aunque comparta palabras comunes.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Iterable, Literal

from app.rag.embeddings import normalize_tokens
from app.rag.retrieval import RetrievedChunk
from app.rag.safety import injection_reason, out_of_scope_reason

_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+|\n+")

# Palabras que forman la pregunta pero no su tema.
_QUERY_FRAME = frozenset(
    """cual cuales cuanto cuanta cuantos cuantas diferencia diferencias significa funciona sirve explica explicame
    ejemplo puedo hago hacer tengo mis mi yo deberia quiero saber hay son esta estan va pasa ocurre sucede calculo
    calcular calcula armo armar what how why which does""".split()
)

AbstentionReason = Literal["no_evidence", "out_of_scope"]


@dataclass(frozen=True)
class Claim:
    text: str
    citation: dict
    score: float


@dataclass(frozen=True)
class EducationalAnswer:
    status: Literal["answered", "abstained"]
    claims: list[Claim]
    abstention_reason: AbstentionReason | None
    coverage: float = 0.0


@dataclass(frozen=True)
class TermStats:
    """Frecuencia de documentos por término sobre los fragmentos utilizables del corpus."""

    document_frequency: dict[str, int]
    documents: int

    @classmethod
    def from_texts(cls, texts: Iterable[str]) -> TermStats:
        df: dict[str, int] = {}
        n = 0
        for text in texts:
            n += 1
            for term in set(normalize_tokens(text)):
                df[term] = df.get(term, 0) + 1
        return cls(df, n)

    def weight(self, term: str) -> float:
        return math.log((self.documents + 1) / (self.document_frequency.get(term, 0) + 0.5)) + 1.0


def query_terms(query: str) -> set[str]:
    return {t for t in normalize_tokens(query) if t not in _QUERY_FRAME}


def split_sentences(text: str) -> list[str]:
    return [s.strip() for s in _SENTENCE_RE.split(text) if len(s.strip()) >= 20]


def compose_answer(
    query: str,
    chunks: list[RetrievedChunk],
    stats: TermStats,
    *,
    max_claims: int = 4,
    min_claim_weight: float = 0.3,
    min_coverage: float = 0.6,
) -> EducationalAnswer:
    if out_of_scope_reason(query):
        return EducationalAnswer("abstained", [], "out_of_scope")
    terms = query_terms(query)
    if not terms or not chunks:
        return EducationalAnswer("abstained", [], "no_evidence")
    weights = {t: stats.weight(t) for t in terms}
    total = sum(weights.values())
    candidates: list[tuple[Claim, set[str]]] = []
    seen: set[str] = set()
    for chunk in chunks:
        for sentence in split_sentences(chunk.content):
            if injection_reason(sentence) or sentence.lower() in seen:
                continue
            matched = terms & set(normalize_tokens(sentence))
            share = sum(weights[t] for t in matched) / total
            if share >= min_claim_weight:
                seen.add(sentence.lower())
                candidates.append((Claim(text=sentence, citation=dict(chunk.metadata), score=round(share, 4)), matched))
    candidates.sort(key=lambda item: item[0].score, reverse=True)
    selected = candidates[:max_claims]
    covered: set[str] = set().union(*(m for _, m in selected)) if selected else set()
    coverage = round(sum(weights[t] for t in covered) / total, 4)
    if not selected or coverage < min_coverage:
        return EducationalAnswer("abstained", [], "no_evidence", coverage)
    return EducationalAnswer("answered", [c for c, _ in selected], None, coverage)
