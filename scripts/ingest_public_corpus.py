"""Ingiero documentos del corpus público curado. No hay ingesta por HTTP.

Uso:
    python scripts/ingest_public_corpus.py --file nota.md      # con encabezado de procedencia
    python scripts/ingest_public_corpus.py --dir corpus/       # todos los .md de una carpeta

Cada documento exige título, editor, fuente, fecha de publicación, de revisión y vigencia.
Solo cargo material público y revisado; nunca documentos de personas usuarias. Los fragmentos
con instrucciones sospechosas quedan registrados pero no se indexan.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import Settings
from app.data.documents import PublicCorpusRepository
from app.db.engine import build_engine
from app.rag.corpus_files import load_curated_dir, parse_curated
from app.rag.ingestion import ingest_public_document
from app.rag.vector_store import IndexRegistry, build_vector_store


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingiero documentos del corpus público curado.")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--file", type=Path)
    group.add_argument("--dir", type=Path)
    args = parser.parse_args()
    settings = Settings()
    engine = build_engine(settings.resolved_database_url())
    corpus = PublicCorpusRepository(engine)
    vector = build_vector_store(settings)
    registry = IndexRegistry(engine)
    docs = load_curated_dir(args.dir) if args.dir else [parse_curated(args.file.read_text(encoding="utf-8"), args.file.stem)]
    for doc in docs:
        result = ingest_public_document(
            settings=settings, corpus=corpus, vector=vector, title=doc.title, content=doc.content, provenance=doc.provenance, registry=registry
        )
        print(f"{doc.slug}: chunks_indexed={result.chunks_indexed} chunks_flagged={result.chunks_flagged}")


if __name__ == "__main__":
    main()
