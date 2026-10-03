"""Casos de uso v1. Cada método recibe la cuenta autenticada; no acepta identificadores de persona."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from app.core.config import Settings
from app.core.observability import log_event
from app.data.accounts import AuditRepository, GoalRepository, ProfileRepository, UserRecord
from app.data.documents import PublicCorpusRepository
from app.data.privacy import PrivacyRepository
from app.rag.retrieval import build_context, retrieve
from app.rag.vector_store import VectorStoreBundle
from app.reasoning.engine import extractive_answer


class NotFoundError(Exception):
    pass


class LimitExceededError(Exception):
    pass


def today_utc() -> date:
    return datetime.now(tz=UTC).date()


def goal_to_v1(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row["id"],
        "name": row["name"],
        "target": {"amount": row["target_amount"], "currency": row["currency"]},
        "saved": {"amount": row["saved_amount"], "currency": row["currency"]},
        "priority": row["priority"],
        "target_date": row["target_date"],
        "horizon_months": row["horizon_months"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def goal_values(payload: dict[str, Any]) -> dict[str, Any]:
    target = payload["target"]
    saved = payload.get("saved") or {"amount": Decimal("0"), "currency": target["currency"]}
    return {
        "name": payload["name"],
        "currency": target["currency"],
        "target_amount": Decimal(str(target["amount"])),
        "saved_amount": Decimal(str(saved["amount"])),
        "priority": payload["priority"],
        "target_date": payload.get("target_date"),
        "horizon_months": payload.get("horizon_months"),
    }


@dataclass(frozen=True)
class AccountService:
    settings: Settings
    profiles: ProfileRepository
    goals: GoalRepository
    audit: AuditRepository
    privacy: PrivacyRepository

    def _audit(self, user: UserRecord, action: str, resource_type: str, outcome: str, resource_id: str | None, request_id: str | None) -> None:
        self.audit.record(
            user_id=user.id, action=action, resource_type=resource_type, outcome=outcome, resource_id=resource_id, request_id=request_id
        )

    # Perfil
    def get_profile(self, user: UserRecord) -> dict[str, Any]:
        stored = self.profiles.get(user.id)
        if stored is None:
            raise NotFoundError("profile")
        return stored

    def put_profile(self, user: UserRecord, data: dict[str, Any], request_id: str | None) -> dict[str, Any]:
        stored = self.profiles.upsert(user.id, data, base_currency=data["currency"])
        self._audit(user, "profile.upsert", "profile", "success", None, request_id)
        return stored

    # Metas
    def list_goals(self, user: UserRecord) -> list[dict[str, Any]]:
        return self.goals.list(user.id)

    def get_goal(self, user: UserRecord, goal_id: str) -> dict[str, Any]:
        goal = self.goals.get(user.id, goal_id)
        if goal is None:
            raise NotFoundError("goal")
        return goal

    def create_goal(self, user: UserRecord, payload: dict[str, Any], request_id: str | None) -> dict[str, Any]:
        if self.goals.count(user.id) >= self.settings.max_goals_per_user:
            raise LimitExceededError("goals")
        goal = self.goals.create(user.id, goal_values(payload))
        self._audit(user, "goal.create", "goal", "success", goal["id"], request_id)
        return goal

    def update_goal(self, user: UserRecord, goal_id: str, payload: dict[str, Any], request_id: str | None) -> dict[str, Any]:
        goal = self.goals.update(user.id, goal_id, goal_values(payload))
        if goal is None:
            self._audit(user, "goal.update", "goal", "not_found", None, request_id)
            raise NotFoundError("goal")
        self._audit(user, "goal.update", "goal", "success", goal_id, request_id)
        return goal

    def delete_goal(self, user: UserRecord, goal_id: str, request_id: str | None) -> None:
        if not self.goals.delete(user.id, goal_id):
            self._audit(user, "goal.delete", "goal", "not_found", None, request_id)
            raise NotFoundError("goal")
        self._audit(user, "goal.delete", "goal", "success", goal_id, request_id)

    # Privacidad
    def export(self, user: UserRecord, request_id: str | None) -> dict[str, Any]:
        self._audit(user, "account.export", "account", "success", None, request_id)
        data = self.privacy.export(user.id)
        data["export_format_version"] = 1
        return data

    def erase(self, user: UserRecord, request_id: str | None) -> dict[str, Any]:
        result = self.privacy.erase(user.id, user.issuer, user.subject)
        # Registro el borrado sin vínculo con la identidad: el usuario ya no existe.
        self.audit.record(
            user_id=user.id, action="account.delete", resource_type="account", outcome="success", resource_id=result["receipt_id"], request_id=request_id
        )
        log_event("account_deleted", request_id=request_id, receipt_id=result["receipt_id"])
        return result


@dataclass(frozen=True)
class KnowledgeService:
    """Preguntas educativas sobre el corpus público. No uso el perfil ni datos de la cuenta."""

    settings: Settings
    corpus: PublicCorpusRepository
    vector: VectorStoreBundle

    def answer(self, query: str, top_k: int | None) -> dict[str, Any]:
        chunks = retrieve(settings=self.settings, corpus=self.corpus, vector=self.vector, query=query, top_k=top_k)
        context, citations = build_context(chunks)
        return {"answer": extractive_answer(query, context), "citations": citations}
