"""Índice vectorial del corpus público, versionado por modelo y dimensión de embeddings.

Cada combinación modelo/dimensión usa su propia colección con distancia coseno. Cambiar de
modelo crea un índice nuevo (`scripts/reindex_corpus.py`) sin sobrescribir el activo.
"""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import Engine, insert, select, update

from app.core.config import Settings
from app.rag.embeddings import EmbeddingSpec, Embeddings, build_embeddings


@dataclass(frozen=True)
class VectorStoreBundle:
    store: object
    embeddings: Embeddings
    spec: EmbeddingSpec

    @property
    def mode(self) -> str:
        return self.spec.mode


def open_collection(settings: Settings, embeddings: Embeddings, spec: EmbeddingSpec) -> object:
    persist_dir = settings.resolved_chroma_dir()
    persist_dir.mkdir(parents=True, exist_ok=True)
    try:
        from langchain_chroma import Chroma

        return Chroma(
            collection_name=spec.collection,
            persist_directory=str(persist_dir),
            embedding_function=embeddings,
            collection_metadata={"hnsw:space": "cosine", "embedding_model": spec.model, "dimension": spec.dimension},
        )
    except Exception as exc:
        raise RuntimeError("Failed to initialize the vector store.") from exc


def build_vector_store(settings: Settings) -> VectorStoreBundle:
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    embeddings, spec = build_embeddings(settings)
    return VectorStoreBundle(store=open_collection(settings, embeddings, spec), embeddings=embeddings, spec=spec)


@dataclass(frozen=True)
class IndexRegistry:
    """Registro en la base de qué índice está activo para cada modelo y dimensión."""

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
