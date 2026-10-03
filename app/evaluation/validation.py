from __future__ import annotations

from typing import Any


def validate_citations(citations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    clean: list[dict[str, Any]] = []
    for c in citations:
        if not isinstance(c, dict):
            continue
        doc_id = c.get("doc_id")
        if not doc_id:
            continue
        clean.append(
            {
                "doc_id": str(doc_id),
                "chunk_id": c.get("chunk_id"),
                "title": c.get("title"),
                "source": c.get("source"),
            }
        )
    seen: set[tuple[str, str | None]] = set()
    out: list[dict[str, Any]] = []
    for c in clean:
        key = (c["doc_id"], c.get("chunk_id"))
        if key in seen:
            continue
        seen.add(key)
        out.append(c)
    return out

