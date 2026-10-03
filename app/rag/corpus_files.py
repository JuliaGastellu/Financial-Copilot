"""Lectura de documentos curados con procedencia en un encabezado simple.

Formato:
    ---
    title: Qué es una reserva de emergencia
    publisher: Nombre de quien publica
    source: https://...
    published_on: 2026-01-15
    reviewed_on: 2026-09-01
    valid_until: 2027-09-01
    ---
    Texto del documento...
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path

from app.data.documents import Provenance

REQUIRED = ("title", "publisher", "source", "published_on", "reviewed_on", "valid_until")


@dataclass(frozen=True)
class CuratedDocument:
    slug: str
    title: str
    content: str
    provenance: Provenance


def parse_curated(text: str, slug: str) -> CuratedDocument:
    if not text.startswith("---"):
        raise ValueError(f"{slug}: missing provenance header.")
    _, header, body = text.split("---", 2)
    fields: dict[str, str] = {}
    for line in header.strip().splitlines():
        key, _, value = line.partition(":")
        fields[key.strip()] = value.strip()
    missing = [k for k in REQUIRED if not fields.get(k)]
    if missing:
        raise ValueError(f"{slug}: missing {', '.join(missing)}.")
    provenance = Provenance(
        publisher=fields["publisher"],
        source=fields["source"],
        published_on=date.fromisoformat(fields["published_on"]),
        reviewed_on=date.fromisoformat(fields["reviewed_on"]),
        valid_until=date.fromisoformat(fields["valid_until"]),
    )
    return CuratedDocument(slug=slug, title=fields["title"], content=body.strip(), provenance=provenance)


def load_curated_dir(directory: Path) -> list[CuratedDocument]:
    return [parse_curated(p.read_text(encoding="utf-8"), p.stem) for p in sorted(directory.glob("*.md"))]
