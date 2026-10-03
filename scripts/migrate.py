"""Aplico o revierto migraciones versionadas de Alembic sobre DATABASE_URL.

Uso:
    python scripts/migrate.py upgrade [--revision head]
    python scripts/migrate.py downgrade --revision <rev|base>
    python scripts/migrate.py current
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Permito ejecutar desde la raíz del proyecto sin instalar el paquete.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import Settings
from app.db.engine import build_engine, current_revision, downgrade, head_revision, upgrade


def main() -> None:
    parser = argparse.ArgumentParser(description="Aplico migraciones de la base de datos.")
    parser.add_argument("action", choices=["upgrade", "downgrade", "current"])
    parser.add_argument("--revision", default=None)
    args = parser.parse_args()
    url = Settings().resolved_database_url()
    if args.action == "upgrade":
        upgrade(url, args.revision or "head")
    elif args.action == "downgrade":
        if not args.revision:
            parser.error("downgrade requires --revision")
        downgrade(url, args.revision)
    engine = build_engine(url)
    print(f"current={current_revision(engine)} head={head_revision(url)}")
    engine.dispose()


if __name__ == "__main__":
    main()
