"""Repositorios de versiones de plan, escenarios, avances e idempotencia.

Los métodos que crean o cambian estado reciben una conexión abierta para que el
servicio pueda agrupar la escritura y la clave de idempotencia en una sola transacción.
"""
from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import Connection, Engine, and_, delete, func, insert, or_, select, update

from app.data.accounts import new_id, utc_now
from app.db.schema import goals, idempotency_keys, plans, progress_entries, scenarios


class InvalidCursorError(ValueError):
    pass


def encode_cursor(values: dict[str, Any]) -> str:
    return base64.urlsafe_b64encode(json.dumps(values, default=str).encode()).decode().rstrip("=")


def decode_cursor(cursor: str, keys: tuple[str, ...]) -> dict[str, Any]:
    try:
        data = json.loads(base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)))
    except Exception as exc:
        raise InvalidCursorError("Invalid cursor.") from exc
    if not isinstance(data, dict) or set(data) != set(keys):
        raise InvalidCursorError("Invalid cursor.")
    return data


def _ts(value: Any) -> datetime:
    from datetime import UTC

    dt = value if isinstance(value, datetime) else datetime.fromisoformat(str(value))
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


@dataclass(frozen=True)
class PlanVersionRepository:
    engine: Engine

    def get(self, owner_id: str, plan_id: str, conn: Connection | None = None) -> dict[str, Any] | None:
        query = select(plans).where(plans.c.id == plan_id, plans.c.user_id == owner_id)
        if conn is not None:
            row = conn.execute(query).mappings().first()
        else:
            with self.engine.connect() as c:
                row = c.execute(query).mappings().first()
        return dict(row) if row else None

    def active(self, owner_id: str) -> dict[str, Any] | None:
        with self.engine.connect() as conn:
            row = conn.execute(select(plans).where(plans.c.user_id == owner_id, plans.c.status == "active")).mappings().first()
            return dict(row) if row else None

    def create_active(self, conn: Connection, owner_id: str, values: dict[str, Any]) -> str:
        """Creo una versión nueva y marco la anterior como reemplazada, en la misma transacción."""
        now = utc_now()
        next_version = int(
            conn.execute(select(func.coalesce(func.max(plans.c.version), 0)).where(plans.c.user_id == owner_id)).scalar_one()
        ) + 1
        conn.execute(
            update(plans)
            .where(plans.c.user_id == owner_id, plans.c.status == "active")
            .values(status="superseded", superseded_at=now)
        )
        plan_id = new_id()
        conn.execute(
            insert(plans).values(id=plan_id, user_id=owner_id, version=next_version, status="active", created_at=now, **values)
        )
        return plan_id

    def page(self, owner_id: str, limit: int, cursor: str | None) -> tuple[list[dict[str, Any]], str | None]:
        query = select(plans).where(plans.c.user_id == owner_id)
        if cursor:
            query = query.where(plans.c.version < int(decode_cursor(cursor, ("v",))["v"]))
        with self.engine.connect() as conn:
            rows = [dict(r) for r in conn.execute(query.order_by(plans.c.version.desc()).limit(limit + 1)).mappings()]
        next_cursor = encode_cursor({"v": rows[limit - 1]["version"]}) if len(rows) > limit else None
        return rows[:limit], next_cursor

    def delete_superseded(self, owner_id: str, plan_id: str) -> str:
        with self.engine.begin() as conn:
            row = conn.execute(select(plans.c.status).where(plans.c.id == plan_id, plans.c.user_id == owner_id)).first()
            if row is None:
                return "not_found"
            if row.status == "active":
                return "active"
            conn.execute(delete(scenarios).where(scenarios.c.base_plan_id == plan_id, scenarios.c.user_id == owner_id))
            conn.execute(delete(plans).where(plans.c.id == plan_id, plans.c.user_id == owner_id))
            return "deleted"


@dataclass(frozen=True)
class ScenarioRepository:
    engine: Engine

    def create(self, conn: Connection, owner_id: str, values: dict[str, Any]) -> str:
        scenario_id = new_id()
        conn.execute(
            insert(scenarios).values(id=scenario_id, user_id=owner_id, status="simulated", created_at=utc_now(), **values)
        )
        return scenario_id

    def get(self, owner_id: str, scenario_id: str, conn: Connection | None = None) -> dict[str, Any] | None:
        query = select(scenarios).where(scenarios.c.id == scenario_id, scenarios.c.user_id == owner_id)
        if conn is not None:
            row = conn.execute(query).mappings().first()
        else:
            with self.engine.connect() as c:
                row = c.execute(query).mappings().first()
        return dict(row) if row else None

    def mark_adopted(self, conn: Connection, owner_id: str, scenario_id: str, plan_id: str) -> bool:
        result = conn.execute(
            update(scenarios)
            .where(scenarios.c.id == scenario_id, scenarios.c.user_id == owner_id, scenarios.c.status == "simulated")
            .values(status="adopted", adopted_plan_id=plan_id, adopted_at=utc_now())
        )
        return result.rowcount == 1

    def page(self, owner_id: str, limit: int, cursor: str | None, base_plan_id: str | None) -> tuple[list[dict[str, Any]], str | None]:
        query = select(scenarios).where(scenarios.c.user_id == owner_id)
        if base_plan_id:
            query = query.where(scenarios.c.base_plan_id == base_plan_id)
        if cursor:
            c = decode_cursor(cursor, ("t", "i"))
            ts = _ts(c["t"])
            query = query.where(or_(scenarios.c.created_at < ts, and_(scenarios.c.created_at == ts, scenarios.c.id < c["i"])))
        with self.engine.connect() as conn:
            rows = [
                dict(r)
                for r in conn.execute(
                    query.order_by(scenarios.c.created_at.desc(), scenarios.c.id.desc()).limit(limit + 1)
                ).mappings()
            ]
        last = rows[limit - 1] if len(rows) > limit else None
        next_cursor = encode_cursor({"t": _ts(last["created_at"]).isoformat(), "i": last["id"]}) if last else None
        return rows[:limit], next_cursor

    def delete_simulated(self, owner_id: str, scenario_id: str) -> str:
        with self.engine.begin() as conn:
            row = conn.execute(
                select(scenarios.c.status).where(scenarios.c.id == scenario_id, scenarios.c.user_id == owner_id)
            ).first()
            if row is None:
                return "not_found"
            if row.status == "adopted":
                return "adopted"
            conn.execute(delete(scenarios).where(scenarios.c.id == scenario_id, scenarios.c.user_id == owner_id))
            return "deleted"


def _progress_row(row: Any) -> dict[str, Any]:
    out = dict(row)
    out["amount"] = Decimal(str(out["amount"])).quantize(Decimal("0.01"))
    return out


@dataclass(frozen=True)
class ProgressRepository:
    engine: Engine

    def create(self, conn: Connection, owner_id: str, values: dict[str, Any]) -> str:
        entry_id = new_id()
        conn.execute(insert(progress_entries).values(id=entry_id, user_id=owner_id, recorded_at=utc_now(), **values))
        return entry_id

    def get(self, owner_id: str, entry_id: str, conn: Connection | None = None) -> dict[str, Any] | None:
        query = select(progress_entries).where(progress_entries.c.id == entry_id, progress_entries.c.user_id == owner_id)
        if conn is not None:
            row = conn.execute(query).mappings().first()
        else:
            with self.engine.connect() as c:
                row = c.execute(query).mappings().first()
        return _progress_row(row) if row else None

    def for_owner(self, owner_id: str) -> list[dict[str, Any]]:
        with self.engine.connect() as conn:
            rows = conn.execute(
                select(progress_entries).where(progress_entries.c.user_id == owner_id).order_by(progress_entries.c.recorded_at)
            ).mappings()
            return [_progress_row(r) for r in rows]

    def for_period(self, owner_id: str, period: date) -> list[dict[str, Any]]:
        with self.engine.connect() as conn:
            rows = conn.execute(
                select(progress_entries).where(progress_entries.c.user_id == owner_id, progress_entries.c.period == period)
            ).mappings()
            return [_progress_row(r) for r in rows]

    def page(
        self, owner_id: str, limit: int, cursor: str | None, goal_id: str | None, period: date | None
    ) -> tuple[list[dict[str, Any]], str | None]:
        query = select(progress_entries).where(progress_entries.c.user_id == owner_id)
        if goal_id:
            query = query.where(progress_entries.c.goal_id == goal_id)
        if period:
            query = query.where(progress_entries.c.period == period)
        if cursor:
            c = decode_cursor(cursor, ("t", "i"))
            ts = _ts(c["t"])
            query = query.where(
                or_(progress_entries.c.recorded_at < ts, and_(progress_entries.c.recorded_at == ts, progress_entries.c.id < c["i"]))
            )
        with self.engine.connect() as conn:
            rows = [
                _progress_row(r)
                for r in conn.execute(
                    query.order_by(progress_entries.c.recorded_at.desc(), progress_entries.c.id.desc()).limit(limit + 1)
                ).mappings()
            ]
        last = rows[limit - 1] if len(rows) > limit else None
        next_cursor = encode_cursor({"t": _ts(last["recorded_at"]).isoformat(), "i": last["id"]}) if last else None
        return rows[:limit], next_cursor

    def delete(self, owner_id: str, entry_id: str) -> bool:
        with self.engine.begin() as conn:
            result = conn.execute(
                delete(progress_entries).where(progress_entries.c.id == entry_id, progress_entries.c.user_id == owner_id)
            )
            return result.rowcount > 0


@dataclass(frozen=True)
class IdempotencyRepository:
    engine: Engine

    def find(self, owner_id: str, key: str) -> dict[str, Any] | None:
        with self.engine.connect() as conn:
            row = conn.execute(
                select(idempotency_keys).where(idempotency_keys.c.user_id == owner_id, idempotency_keys.c.key == key)
            ).mappings().first()
            return dict(row) if row else None

    def store(self, conn: Connection, owner_id: str, key: str, *, operation: str, request_hash: str, resource_type: str, resource_id: str) -> None:
        conn.execute(
            insert(idempotency_keys).values(
                user_id=owner_id,
                key=key,
                operation=operation,
                request_hash=request_hash,
                resource_type=resource_type,
                resource_id=resource_id,
                created_at=utc_now(),
            )
        )


def goal_contributions(conn: Connection, owner_id: str) -> list[dict[str, Any]]:
    """Aportes por meta con la fecha de su último ahorro declarado, para el cálculo de saldos."""
    rows = conn.execute(
        select(
            progress_entries.c.goal_id,
            progress_entries.c.amount,
            progress_entries.c.currency,
            progress_entries.c.source,
            progress_entries.c.recorded_at,
            goals.c.saved_as_of,
        )
        .join(goals, goals.c.id == progress_entries.c.goal_id)
        .where(progress_entries.c.user_id == owner_id, goals.c.user_id == owner_id)
    ).mappings()
    return [_progress_row(r) for r in rows]
