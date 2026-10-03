"""Ingiero un documento del corpus público curado. No hay ingesta por HTTP.

Uso:
    python scripts/ingest_public_corpus.py --file nota.md --title "Título" --source "https://fuente"

Solo cargo material público y revisado; nunca documentos de personas usuarias.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import Settings
from app.data.documents import PublicCorpusRepository
from app.db.engine import build_engine
from app.rag.ingestion import ingest_public_document
from app.rag.vector_store import build_vector_store


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingiero un documento del corpus público.")
    parser.add_argument("--file", type=Path, required=True)
    parser.add_argument("--title", required=True)
    parser.add_argument("--source", required=True, help="URL o referencia pública del material.")
    args = parser.parse_args()
    settings = Settings()
    engine = build_engine(settings.resolved_database_url())
    text = args.file.read_text(encoding="utf-8")
    if args.file.suffix.lower() in (".html", ".htm"):
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(text, "html.parser")
        for tag in soup(["script", "style", "nav", "footer", "head"]):
            tag.decompose()
        text = soup.get_text(separator="\n", strip=True)
    result = ingest_public_document(
        settings=settings,
        corpus=PublicCorpusRepository(engine),
        vector=build_vector_store(settings),
        title=args.title,
        source=args.source,
        content=text,
    )
    print(f"doc_id={result.doc_id} chunks_indexed={result.chunks_indexed}")


if __name__ == "__main__":
    main()
