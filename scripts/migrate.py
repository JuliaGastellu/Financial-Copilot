"""Apply the current schema to the configured SQLite database.

Usage:
    python scripts/migrate.py [--db-path PATH]

All DDL statements use CREATE TABLE/INDEX IF NOT EXISTS, so this script is safe
to run multiple times (idempotent). For additive changes (new columns), add
ALTER TABLE statements below the baseline DDL and guard them with a try/except.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Allow running from project root without installing the package
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import settings
from app.data.sqlite import SqliteDb


def migrate(db_path: Path) -> None:
    db = SqliteDb(path=db_path)
    db.init_schema()
    print(f"Schema applied to: {db_path}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Apply database schema migrations.")
    parser.add_argument("--db-path", type=Path, default=None, help="Path to SQLite database file.")
    args = parser.parse_args()

    db_path = args.db_path or settings.resolved_sqlite_path()
    migrate(db_path)


if __name__ == "__main__":
    main()
