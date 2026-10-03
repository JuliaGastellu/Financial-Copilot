"""Índice vectorial del corpus público en la base relacional, versionado por modelo y dimensión.

En PostgreSQL uso pgvector con búsqueda exacta por distancia coseno: para un corpus curado de
este tamaño la búsqueda exacta es suficiente y evita depender de parámetros de índices
aproximados. En SQLite (desarrollo y pruebas) calculo la misma similitud en Python.
Los filtros de corpus, aprobación, vigencia y marcas van dentro de la consulta.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date
from typing import Any

from sqlalchemy import Engine, bindparam, insert, select, text, update

from app.core.config import Settings
from app.data.documents import _CHUNK_COLUMNS, _usable
from app.db.schema import chunk_embeddings, chunks, documents
from app.rag.embeddings import EmbeddingSpec, Embeddings, build_embeddings


@dataclass(frozen=True)
class VectorStoreBundle:
    store: SqlVectorStore
    embeddings: Embeddings
    spec: EmbeddingSpec

    @property
    def mode(self) -> str:
        return self.spec.mode


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


@dataclass(frozen=True)
class SqlVectorStore:
    engine: Engine
    embeddings: Embeddings
    spec: EmbeddingSpec

    def _model_filter(self) -> Any:
        return (chunk_embeddings.c.embedding_model == self.spec.model) & (chunk_embeddings.c.dimension == self.spec.dimension)

    def existing_ids(self) -> set[str]:
        with self.engine.connect() as conn:
            return {r[0] for r in conn.execute(select(chunk_embeddings.c.chunk_id).where(self._model_filter()))}

    def add(self, items: list[tuple[str, str]]) -> int:
        """Guardo embeddings de (chunk_id, texto). Ignoro los que ya existen para este modelo."""
        if not items:
            return 0
        existing = self.existing_ids()
        pending = [(cid, txt) for cid, txt in items if cid not in existing]
        if not pending:
            return 0
        vectors = self.embeddings.embed_documents([txt for _, txt in pending])
        from app.data.accounts import utc_now

        now = utc_now()
        with self.engine.begin() as conn:
            conn.execute(
                insert(chunk_embeddings),
                [
                    {"chunk_id": cid, "embedding_model": self.spec.model, "dimension": self.spec.dimension, "embedding": vec, "created_at": now}
                    for (cid, _), vec in zip(pending, vectors)
                ],
            )
        return len(pending)

    def search(self, query: str, k: int, today: date) -> list[tuple[dict[str, Any], float]]:
        vector = self.embeddings.embed_query(query)
        if self.engine.dialect.name == "postgresql":
            return self._search_pg(vector, k, today)
        return self._search_local(vector, k, today)

    def _search_pg(self, vector: list[float], k: int, today: date) -> list[tuple[dict[str, Any], float]]:
        literal = "[" + ",".join(f"{x:.7g}" for x in vector) + "]"
        distance = text("chunk_embeddings.embedding <=> CAST(:qvec AS vector)").bindparams(bindparam("qvec", literal))
        stmt = (
            select(*_CHUNK_COLUMNS, distance.label("distance"))
            .join(documents, documents.c.id == chunks.c.document_id)
            .join(chunk_embeddings, chunk_embeddings.c.chunk_id == chunks.c.id)
            .where(_usable(today), self._model_filter())
            .order_by(text("distance"))
            .limit(k)
        )
        with self.engine.connect() as conn:
            rows = conn.execute(stmt).mappings().all()
        return [({k2: v for k2, v in r.items() if k2 != "distance"}, 1.0 - float(r["distance"])) for r in rows]

    def _search_local(self, vector: list[float], k: int, today: date) -> list[tuple[dict[str, Any], float]]:
        stmt = (
            select(*_CHUNK_COLUMNS, chunk_embeddings.c.embedding)
            .join(documents, documents.c.id == chunks.c.document_id)
            .join(chunk_embeddings, chunk_embeddings.c.chunk_id == chunks.c.id)
            .where(_usable(today), self._model_filter())
        )
        with self.engine.connect() as conn:
            rows = conn.execute(stmt).mappings().all()
        scored = [({k2: v for k2, v in r.items() if k2 != "embedding"}, _cosine(vector, r["embedding"])) for r in rows]
        scored.sort(key=lambda item: item[1], reverse=True)
        return scored[:k]

    def ping(self) -> None:
        with self.engine.connect() as conn:
            conn.execute(select(chunk_embeddings.c.chunk_id).limit(1)).first()


def build_vector_store(settings: Settings, engine: Engine) -> VectorStoreBundle:
    embeddings, spec = build_embeddings(settings)
    return VectorStoreBundle(store=SqlVectorStore(engine, embeddings, spec), embeddings=embeddings, spec=spec)


@dataclass(frozen=True)
class IndexRegistry:
    """Registro de qué modelo de embeddings está activo para el corpus."""

    engine: Engine

    def active(self) -> dict | None:
        from app.db.schema import vector_indexes

        with self.engine.connect() as conn:
            row = conn.execute(select(vector_indexes).where(vector_indexes.c.status == "active")).mappings().first()
            return dict(row) if row else None

    def ensure(self, spec: EmbeddingSpec, chunk_count: int) -> None:
        """Marco el índice de este modelo como activo y retiro los demás."""
        from app.data.accounts import new_id, utc_now
        from app.db.schema import vector_indexes

        with self.engine.begin() as conn:
            row = conn.execute(
                select(vector_indexes.c.id).where(
                    vector_indexes.c.embedding_model == spec.model, vector_indexes.c.dimension == spec.dimension
                )
            ).first()
            conn.execute(update(vector_indexes).where(vector_indexes.c.status == "active").values(status="retired"))
            if row is None:
                conn.execute(
                    insert(vector_indexes).values(
                        id=new_id(),
                        embedding_model=spec.model,
                        dimension=spec.dimension,
                        collection=spec.collection,
                        status="active",
                        chunk_count=chunk_count,
                        created_at=utc_now(),
                    )
                )
            else:
                conn.execute(update(vector_indexes).where(vector_indexes.c.id == row.id).values(status="active", chunk_count=chunk_count))

    def matches(self, spec: EmbeddingSpec) -> bool:
        active = self.active()
        return active is None or (active["embedding_model"] == spec.model and active["dimension"] == spec.dimension)
