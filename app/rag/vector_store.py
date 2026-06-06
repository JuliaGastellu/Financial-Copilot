from __future__ import annotations

from dataclasses import dataclass

from app.core.config import Settings
from app.rag.embeddings import Embeddings, build_embeddings


@dataclass(frozen=True)
class VectorStoreBundle:
    store: object
    embeddings: Embeddings
    mode: str


def build_vector_store(settings: Settings) -> VectorStoreBundle:
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    persist_dir = settings.resolved_chroma_dir()
    persist_dir.mkdir(parents=True, exist_ok=True)
    embeddings, mode = build_embeddings(settings)

    try:
        try:
            from langchain_chroma import Chroma
        except ImportError:
            from langchain_community.vectorstores import Chroma  # type: ignore[no-redef]

        store = Chroma(
            collection_name=settings.chroma_collection,
            persist_directory=str(persist_dir),
            embedding_function=embeddings,
        )
    except Exception as exc:
        raise RuntimeError("Failed to initialize ChromaDB vector store.") from exc
    return VectorStoreBundle(store=store, embeddings=embeddings, mode=mode)
