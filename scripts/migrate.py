"""Aplico el esquema actual a la base SQLite configurada.

Uso este comando:
    python scripts/migrate.py [--db-path PATH]

Uso CREATE TABLE/INDEX IF NOT EXISTS para poder repetir la aplicación del esquema.
Para futuros cambios de columnas necesito migraciones explícitas y versionadas;
este script solo aplica el esquema base actual.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Permito ejecutar desde la raíz del proyecto sin instalar el paquete.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import settings
from app.data.sqlite import SqliteDb


def migrate(db_path: Path) -> None:
    db = SqliteDb(path=db_path)
    db.init_schema()
    print(f"Schema applied to: {db_path}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Aplico el esquema base de la base de datos.")
    parser.add_argument("--db-path", type=Path, default=None, help="Indico la ruta al archivo SQLite.")
    args = parser.parse_args()

    db_path = args.db_path or settings.resolved_sqlite_path()
    migrate(db_path)


if __name__ == "__main__":
    main()
