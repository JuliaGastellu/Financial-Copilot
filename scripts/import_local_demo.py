"""Importo perfiles de demostración ficticios del SQLite local anterior a una cuenta.

Uso (simulación por defecto; no escribe):
    python scripts/import_local_demo.py --sqlite data/app.db --legacy-user demo-user \
        --issuer https://issuer.example --subject <sub> --i-confirm-fictitious-data
Agrego --apply para escribir. La salida muestra solo conteos, nunca contenido.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import Settings
from app.data.accounts import GoalRepository, ProfileRepository, UserRepository
from app.data.demo_import import legacy_profile_to_v1, read_legacy_profiles
from app.db.engine import build_engine
from app.services.accounts import goal_values


def main() -> None:
    parser = argparse.ArgumentParser(description="Importación controlada de perfiles de demostración.")
    parser.add_argument("--sqlite", type=Path, required=True)
    parser.add_argument("--legacy-user", action="append", required=True, help="Identificador del perfil ficticio; repetible.")
    parser.add_argument("--issuer", required=True)
    parser.add_argument("--subject", required=True)
    parser.add_argument("--i-confirm-fictitious-data", action="store_true")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    if not args.i_confirm_fictitious_data:
        parser.error("Refusing to import: confirm that the profiles are fictitious demo data.")
    if len(args.legacy_user) != 1:
        parser.error("Import one legacy profile per account.")
    profiles = read_legacy_profiles(args.sqlite, args.legacy_user)
    if not profiles:
        print("profiles_found=0")
        return
    profile_v1, goals = legacy_profile_to_v1(next(iter(profiles.values())))
    print(f"profiles_found={len(profiles)} goals={len(goals)} apply={args.apply}")
    if not args.apply:
        return
    engine = build_engine(Settings().resolved_database_url())
    user = UserRepository(engine).get_or_create(args.issuer, args.subject)
    if ProfileRepository(engine).get(user.id) is not None:
        parser.error("Refusing to import: the account already has a profile.")
    ProfileRepository(engine).upsert(user.id, profile_v1, base_currency=profile_v1["currency"])
    repo = GoalRepository(engine)
    for goal in goals:
        repo.create(user.id, goal_values(goal))
    print(f"imported_profiles=1 imported_goals={len(goals)}")


if __name__ == "__main__":
    main()
