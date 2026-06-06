from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.data.sqlite import SqliteDb, dumps_json, loads_json, query_one, utc_now_iso


@dataclass(frozen=True)
class ProfileRepository:
    db: SqliteDb

    def upsert(self, user_id: str, profile: dict[str, Any]) -> dict[str, Any]:
        now = utc_now_iso()
        payload = dumps_json(profile)
        with self.db.connect() as conn:
            row = query_one(conn, "SELECT user_id FROM profiles WHERE user_id = ?", (user_id,))
            if row is None:
                conn.execute(
                    "INSERT INTO profiles (user_id, profile_json, created_at, updated_at) VALUES (?, ?, ?, ?)",
                    (user_id, payload, now, now),
                )
            else:
                conn.execute(
                    "UPDATE profiles SET profile_json = ?, updated_at = ? WHERE user_id = ?",
                    (payload, now, user_id),
                )
        return profile

    def get(self, user_id: str) -> dict[str, Any] | None:
        with self.db.connect() as conn:
            row = query_one(conn, "SELECT profile_json FROM profiles WHERE user_id = ?", (user_id,))
            if row is None:
                return None
            return loads_json(row["profile_json"])

