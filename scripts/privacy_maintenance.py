"""Tareas de privacidad sin contenido financiero en la salida.

Uso:
    python scripts/privacy_maintenance.py retention
    python scripts/privacy_maintenance.py export-receipts --out receipts.json
    python scripts/privacy_maintenance.py reapply-deletions --receipts receipts.json

Procedimiento ante un restore: exporto los recibos de la base vigente antes de restaurar,
restauro el backup, aplico migraciones y reaplico los borrados con esos recibos.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import Settings
from app.data.privacy import PrivacyRepository
from app.db.engine import build_engine


def main() -> None:
    parser = argparse.ArgumentParser(description="Tareas de privacidad.")
    parser.add_argument("action", choices=["retention", "export-receipts", "reapply-deletions"])
    parser.add_argument("--out", type=Path)
    parser.add_argument("--receipts", type=Path)
    args = parser.parse_args()
    settings = Settings()
    repo = PrivacyRepository(build_engine(settings.resolved_database_url()), settings)
    if args.action == "retention":
        print(json.dumps(repo.apply_retention()))
    elif args.action == "export-receipts":
        if not args.out:
            parser.error("--out is required")
        receipts = repo.export_receipts()
        args.out.write_text(json.dumps(receipts), encoding="utf-8")
        print(json.dumps({"receipts": len(receipts)}))
    else:
        if not args.receipts:
            parser.error("--receipts is required")
        print(json.dumps(repo.reapply_deletions(json.loads(args.receipts.read_text(encoding="utf-8")))))


if __name__ == "__main__":
    main()
