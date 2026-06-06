from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from app.data.sqlite import SqliteDb, dumps_json, loads_json, query_all, utc_now_iso


@dataclass(frozen=True)
class DecisionRepository:
    db: SqliteDb

    def create(self, *, user_id: str, decision: dict[str, Any]) -> dict[str, Any]:
        decision_id = str(uuid.uuid4())
        created_at = utc_now_iso()
        payload = dict(decision)
        payload["decision_id"] = decision_id
        payload["user_id"] = user_id
        payload["created_at"] = created_at
        with self.db.connect() as conn:
            conn.execute(
                "INSERT INTO decisions (decision_id, user_id, created_at, decision_json) VALUES (?, ?, ?, ?)",
                (decision_id, user_id, created_at, dumps_json(payload)),
            )
        return payload

    def list_for_user(self, *, user_id: str, limit: int = 50) -> list[dict[str, Any]]:
        with self.db.connect() as conn:
            rows = query_all(
                conn,
                "SELECT decision_json FROM decisions WHERE user_id = ? ORDER BY created_at DESC LIMIT ?",
                (user_id, limit),
            )
        return [loads_json(r["decision_json"]) for r in rows]

