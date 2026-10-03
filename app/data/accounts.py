"""Repositorios con propietario obligatorio.

Cada consulta sobre datos personales incluye `user_id = :owner` en el WHERE. Un recurso
de otra persona se comporta igual que uno inexistente.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import Engine, delete, func, insert, select, update
from sqlalchemy.exc import IntegrityError

from app.db.schema import audit_events, goals, profiles, users

PROFILE_SCHEMA_VERSION = 1


def utc_now() -> datetime:
    return datetime.now(tz=UTC)


def new_id() -> str:
    return str(uuid.uuid4())


@dataclass(frozen=True)
class UserRecord:
    id: str
    issuer: str
    subject: str
    created_at: datetime


@dataclass(frozen=True)
class UserRepository:
    engine: Engine

    def _find(self, issuer: str, subject: str) -> UserRecord | None:
        with self.engine.connect() as conn:
            row = conn.execute(select(users).where(users.c.issuer == issuer, users.c.subject == subject)).mappings().first()
        return UserRecord(row["id"], row["issuer"], row["subject"], row["created_at"]) if row else None

    def get_or_create(self, issuer: str, subject: str) -> UserRecord:
        now = utc_now()
        found = self._find(issuer, subject)
        if found is not None:
            with self.engine.begin() as conn:
                conn.execute(update(users).where(users.c.id == found.id).values(last_seen_at=now))
            return found
        user_id = new_id()
        try:
            with self.engine.begin() as conn:
                conn.execute(insert(users).values(id=user_id, issuer=issuer, subject=subject, created_at=now, last_seen_at=now))
            return UserRecord(user_id, issuer, subject, now)
        except IntegrityError:
            # Otra solicitud creó la cuenta en paralelo; uso la existente.
            existing = self._find(issuer, subject)
            if existing is None:
                raise
            return existing

    def get(self, owner_id: str) -> dict[str, Any] | None:
        with self.engine.connect() as conn:
            row = conn.execute(select(users).where(users.c.id == owner_id)).mappings().first()
            return dict(row) if row else None


@dataclass(frozen=True)
class ProfileRepository:
    engine: Engine

    def get(self, owner_id: str) -> dict[str, Any] | None:
        with self.engine.connect() as conn:
            row = conn.execute(select(profiles).where(profiles.c.user_id == owner_id)).mappings().first()
            return dict(row) if row else None

    def upsert(self, owner_id: str, data: dict[str, Any], base_currency: str) -> dict[str, Any]:
        now = utc_now()
        with self.engine.begin() as conn:
            exists = conn.execute(select(profiles.c.user_id).where(profiles.c.user_id == owner_id)).first()
            if exists:
                conn.execute(
                    update(profiles)
                    .where(profiles.c.user_id == owner_id)
                    .values(data=data, base_currency=base_currency, schema_version=PROFILE_SCHEMA_VERSION, updated_at=now)
                )
            else:
                conn.execute(
                    insert(profiles).values(
                        user_id=owner_id,
                        data=data,
                        base_currency=base_currency,
                        schema_version=PROFILE_SCHEMA_VERSION,
                        created_at=now,
                        updated_at=now,
                    )
                )
        stored = self.get(owner_id)
        assert stored is not None
        return stored


def _goal_row(row: Any) -> dict[str, Any]:
    out = dict(row)
    for key in ("target_amount", "saved_amount"):
        out[key] = Decimal(str(out[key])).quantize(Decimal("0.01"))
    return out


@dataclass(frozen=True)
class GoalRepository:
    engine: Engine

    def list(self, owner_id: str) -> list[dict[str, Any]]:
        with self.engine.connect() as conn:
            rows = conn.execute(
                select(goals).where(goals.c.user_id == owner_id).order_by(goals.c.created_at, goals.c.id)
            ).mappings()
            return [_goal_row(r) for r in rows]

    def count(self, owner_id: str) -> int:
        with self.engine.connect() as conn:
            return int(conn.execute(select(func.count()).select_from(goals).where(goals.c.user_id == owner_id)).scalar_one())

    def get(self, owner_id: str, goal_id: str) -> dict[str, Any] | None:
        with self.engine.connect() as conn:
            row = conn.execute(select(goals).where(goals.c.id == goal_id, goals.c.user_id == owner_id)).mappings().first()
            return _goal_row(row) if row else None

    def create(self, owner_id: str, values: dict[str, Any]) -> dict[str, Any]:
        now = utc_now()
        goal_id = new_id()
        with self.engine.begin() as conn:
            conn.execute(
                insert(goals).values(id=goal_id, user_id=owner_id, created_at=now, updated_at=now, saved_as_of=now, **values)
            )
        stored = self.get(owner_id, goal_id)
        assert stored is not None
        return stored

    def update(self, owner_id: str, goal_id: str, values: dict[str, Any]) -> dict[str, Any] | None:
        current = self.get(owner_id, goal_id)
        if current is None:
            return None
        now = utc_now()
        extra: dict[str, Any] = {"updated_at": now}
        # Si cambia el ahorro declarado, asumo que ya incluye los aportes registrados hasta ahora.
        if Decimal(str(values.get("saved_amount", current["saved_amount"]))) != current["saved_amount"]:
            extra["saved_as_of"] = now
        with self.engine.begin() as conn:
            result = conn.execute(
                update(goals).where(goals.c.id == goal_id, goals.c.user_id == owner_id).values(**extra, **values)
            )
            if result.rowcount == 0:
                return None
        return self.get(owner_id, goal_id)

    def delete(self, owner_id: str, goal_id: str) -> bool:
        with self.engine.begin() as conn:
            result = conn.execute(delete(goals).where(goals.c.id == goal_id, goals.c.user_id == owner_id))
            return result.rowcount > 0


@dataclass(frozen=True)
class AuditRepository:
    engine: Engine

    def record(
        self,
        *,
        user_id: str | None,
        action: str,
        resource_type: str,
        outcome: str,
        resource_id: str | None = None,
        request_id: str | None = None,
    ) -> None:
        with self.engine.begin() as conn:
            conn.execute(
                insert(audit_events).values(
                    id=new_id(),
                    occurred_at=utc_now(),
                    user_id=user_id,
                    action=action,
                    resource_type=resource_type,
                    resource_id=resource_id,
                    outcome=outcome,
                    request_id=(request_id or "")[:64] or None,
                )
            )

    def list_for_user(self, owner_id: str) -> list[dict[str, Any]]:
        with self.engine.connect() as conn:
            rows = conn.execute(
                select(audit_events).where(audit_events.c.user_id == owner_id).order_by(audit_events.c.occurred_at)
            ).mappings()
            return [dict(r) for r in rows]
