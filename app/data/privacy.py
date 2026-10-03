"""Exportación, borrado con evidencia, retención y reaplicación de borrados tras un restore.

Almacenes activos con datos personales: solo la base relacional (users, profiles, goals, plans).
El índice vectorial contiene únicamente el corpus público. La auditoría no guarda contenido
financiero y conserva un identificador interno sin vínculo con la identidad tras el borrado.
"""
from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import Engine, delete, func, insert, select

from app.core.config import Settings
from app.data.accounts import new_id, utc_now
from app.db.schema import (
    audit_events,
    deletion_receipts,
    explanation_usage,
    goals,
    idempotency_keys,
    plan_explanations,
    plans,
    profiles,
    progress_entries,
    scenarios,
    users,
)

# Conservo las claves de idempotencia lo suficiente para cubrir reintentos.
IDEMPOTENCY_RETENTION_DAYS = 7

# Clave fija solo para local y test; producción exige PRIVACY_HASH_KEY.
_DEV_HASH_KEY = "local-development-only-privacy-hash-key"


def privacy_key(settings: Settings) -> str:
    if settings.privacy_hash_key:
        return settings.privacy_hash_key
    if settings.environment == "production":
        raise RuntimeError("PRIVACY_HASH_KEY is required in production.")
    return _DEV_HASH_KEY


def subject_hash(key: str, issuer: str, subject: str) -> str:
    return hmac.new(key.encode("utf-8"), f"{issuer}\n{subject}".encode("utf-8"), hashlib.sha256).hexdigest()


def _count(conn: Any, table: Any, column: Any, owner_id: str) -> int:
    return int(conn.execute(select(func.count()).select_from(table).where(column == owner_id)).scalar_one())


# Orden de borrado: primero las tablas que dependen de otras.
_PERSONAL = (
    ("explanation_usage", explanation_usage, explanation_usage.c.user_id),
    ("plan_explanations", plan_explanations, plan_explanations.c.user_id),
    ("idempotency_keys", idempotency_keys, idempotency_keys.c.user_id),
    ("progress_entries", progress_entries, progress_entries.c.user_id),
    ("scenarios", scenarios, scenarios.c.user_id),
    ("plans", plans, plans.c.user_id),
    ("goals", goals, goals.c.user_id),
    ("profiles", profiles, profiles.c.user_id),
    ("users", users, users.c.id),
)


def _personal_counts(conn: Any, owner_id: str) -> dict[str, int]:
    return {name: _count(conn, table, column, owner_id) for name, table, column in _PERSONAL}


@dataclass(frozen=True)
class PrivacyRepository:
    engine: Engine
    settings: Settings

    def export(self, owner_id: str) -> dict[str, Any]:
        with self.engine.connect() as conn:
            user = conn.execute(select(users).where(users.c.id == owner_id)).mappings().first()
            profile = conn.execute(select(profiles).where(profiles.c.user_id == owner_id)).mappings().first()
            goal_rows = conn.execute(select(goals).where(goals.c.user_id == owner_id).order_by(goals.c.created_at)).mappings().all()
            plan_rows = conn.execute(select(plans).where(plans.c.user_id == owner_id).order_by(plans.c.version)).mappings().all()
            scenario_rows = conn.execute(
                select(scenarios).where(scenarios.c.user_id == owner_id).order_by(scenarios.c.created_at)
            ).mappings().all()
            explanation_rows = conn.execute(
                select(plan_explanations).where(plan_explanations.c.user_id == owner_id).order_by(plan_explanations.c.created_at)
            ).mappings().all()
            progress_rows = conn.execute(
                select(progress_entries).where(progress_entries.c.user_id == owner_id).order_by(progress_entries.c.recorded_at)
            ).mappings().all()
            audit_rows = conn.execute(
                select(audit_events).where(audit_events.c.user_id == owner_id).order_by(audit_events.c.occurred_at)
            ).mappings().all()
        return {
            "user": dict(user) if user else None,
            "profile": dict(profile) if profile else None,
            "goals": [dict(r) for r in goal_rows],
            "plans": [dict(r) for r in plan_rows],
            "scenarios": [dict(r) for r in scenario_rows],
            "progress_entries": [dict(r) for r in progress_rows],
            "plan_explanations": [dict(r) for r in explanation_rows],
            "audit_events": [dict(r) for r in audit_rows],
        }

    def erase(self, owner_id: str, issuer: str, subject: str) -> dict[str, Any]:
        """Borro en una transacción y verifico que no queden filas personales antes de confirmar."""
        now = utc_now()
        with self.engine.begin() as conn:
            before = _personal_counts(conn, owner_id)
            for _name, table, column in _PERSONAL:
                conn.execute(delete(table).where(column == owner_id))
            after = _personal_counts(conn, owner_id)
            if any(after.values()):
                raise RuntimeError("Personal rows remain after deletion; rolling back.")
            retained_audit = _count(conn, audit_events, audit_events.c.user_id, owner_id)
            evidence = {
                "relational_database": {"deleted": before, "remaining": after},
                "vector_store": {"personal_records": 0, "reason": "Private document ingestion is disabled; the index only holds the public corpus."},
                "audit_events": {
                    "retained": retained_audit,
                    "reason": "Pseudonymous internal id without financial content; removed after AUDIT_RETENTION_DAYS.",
                    "retention_days": self.settings.audit_retention_days,
                },
                "application_logs": {"reason": "Logs carry the internal id and request metadata only, never profile, goal or plan content."},
                "backups": {
                    "retention_days": self.settings.backup_retention_days,
                    "reason": "Older backups still contain the data until they expire; this receipt is reapplied after any restore.",
                },
            }
            receipt_id = new_id()
            conn.execute(
                insert(deletion_receipts).values(
                    id=receipt_id,
                    subject_hash=subject_hash(privacy_key(self.settings), issuer, subject),
                    deleted_at=now,
                    evidence=evidence,
                )
            )
        return {"receipt_id": receipt_id, "deleted_at": now.isoformat(), "evidence": evidence}

    def export_receipts(self) -> list[dict[str, Any]]:
        with self.engine.connect() as conn:
            rows = conn.execute(
                select(deletion_receipts.c.id, deletion_receipts.c.subject_hash, deletion_receipts.c.deleted_at)
            ).mappings().all()
        return [{"id": r["id"], "subject_hash": r["subject_hash"], "deleted_at": _iso(r["deleted_at"])} for r in rows]

    def reapply_deletions(self, receipts: list[dict[str, Any]]) -> dict[str, Any]:
        """Tras restaurar un backup, vuelvo a borrar cuentas que tenían recibo de borrado.

        Solo borro cuentas creadas antes del borrado registrado: una cuenta nueva con la
        misma identidad, creada después, no se toca.
        """
        key = privacy_key(self.settings)
        by_hash: dict[str, datetime] = {}
        for r in receipts:
            deleted_at = _parse(r["deleted_at"])
            by_hash[r["subject_hash"]] = max(by_hash.get(r["subject_hash"], deleted_at), deleted_at)
        with self.engine.connect() as conn:
            accounts = conn.execute(select(users.c.id, users.c.issuer, users.c.subject, users.c.created_at)).mappings().all()
        reapplied: list[str] = []
        for account in accounts:
            deleted_at = by_hash.get(subject_hash(key, account["issuer"], account["subject"]))
            if deleted_at is not None and _aware(account["created_at"]) <= deleted_at:
                with self.engine.begin() as conn:
                    for _name, table, column in _PERSONAL:
                        conn.execute(delete(table).where(column == account["id"]))
                reapplied.append(account["id"])
        existing = {r["id"] for r in self.export_receipts()}
        missing = [r for r in receipts if r["id"] not in existing]
        if missing:
            with self.engine.begin() as conn:
                for r in missing:
                    conn.execute(
                        insert(deletion_receipts).values(
                            id=r["id"], subject_hash=r["subject_hash"], deleted_at=_parse(r["deleted_at"]), evidence={"restored_receipt": True}
                        )
                    )
        return {"accounts_deleted_again": len(reapplied), "receipts_restored": len(missing)}

    def apply_retention(self, now: datetime | None = None) -> dict[str, int]:
        now = now or utc_now()
        plan_cutoff = now - timedelta(days=self.settings.plan_retention_days)
        audit_cutoff = now - timedelta(days=self.settings.audit_retention_days)
        # Conservo los recibos mientras pueda existir un backup anterior al borrado, más un margen.
        receipt_cutoff = now - timedelta(days=self.settings.backup_retention_days + 30)
        with self.engine.begin() as conn:
            # Nunca borro el plan vigente por antigüedad: solo versiones reemplazadas.
            old_plans = select(plans.c.id).where(plans.c.created_at < plan_cutoff, plans.c.status == "superseded")
            conn.execute(delete(scenarios).where(scenarios.c.base_plan_id.in_(old_plans)))
            removed_plans = conn.execute(
                delete(plans).where(plans.c.created_at < plan_cutoff, plans.c.status == "superseded")
            ).rowcount
            removed_keys = conn.execute(
                delete(idempotency_keys).where(idempotency_keys.c.created_at < now - timedelta(days=IDEMPOTENCY_RETENTION_DAYS))
            ).rowcount
            removed_audit = conn.execute(delete(audit_events).where(audit_events.c.occurred_at < audit_cutoff)).rowcount
            removed_receipts = conn.execute(delete(deletion_receipts).where(deletion_receipts.c.deleted_at < receipt_cutoff)).rowcount
        return {
            "plans": removed_plans,
            "audit_events": removed_audit,
            "deletion_receipts": removed_receipts,
            "idempotency_keys": removed_keys,
        }


def _aware(value: datetime) -> datetime:
    from datetime import UTC

    return value if value.tzinfo else value.replace(tzinfo=UTC)


def _parse(value: Any) -> datetime:
    return _aware(value if isinstance(value, datetime) else datetime.fromisoformat(str(value)))


def _iso(value: Any) -> str:
    return _aware(value).isoformat() if isinstance(value, datetime) else str(value)
