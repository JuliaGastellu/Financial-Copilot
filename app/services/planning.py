"""Casos de uso de planes versionados, escenarios, avances y revisión mensual.

Reglas que mantengo:
- Un plan vigente por cuenta. Crear un plan o adoptar un escenario son acciones explícitas
  que generan una versión nueva; la anterior queda reemplazada, nunca se edita.
- Un escenario se calcula sobre el snapshot de un plan y no lo modifica.
- Un aporte registrado se cuenta una sola vez: suma al ahorro de su meta hasta que la persona
  actualiza el ahorro declarado de esa meta, y si salió del excedente mensual suma al saldo
  líquido hasta que la persona actualiza los saldos de su perfil.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any, Callable

from sqlalchemy import Connection, Engine
from sqlalchemy.exc import IntegrityError

from app.core.observability import log_event
from app.data.accounts import AuditRepository, GoalRepository, ProfileRepository, UserRecord
from app.data.planning import (
    IdempotencyRepository,
    PlanVersionRepository,
    ProgressRepository,
    ScenarioRepository,
    goal_contributions,
)
from app.finance import ENGINE_VERSION
from app.finance.adapters import snapshot_from_profile
from app.finance.planning import Scenario, apply_scenario, build_plan, run_scenarios
from app.finance.policy import DEFAULT_POLICY
from app.finance.serialization import plan_to_dict
from app.schemas.plans_v1 import (
    SNAPSHOT_SCHEMA_VERSION,
    AmountV1,
    ComparisonBudgetV1,
    ComparisonGoalV1,
    CurrentPlanV1,
    FreshnessV1,
    GoalSnapshotV1,
    MonthlyReviewV1,
    PlanResultV1,
    PlanSnapshotV1,
    PlanSummaryV1,
    PlanV1,
    ProgressEntryV1,
    ReproductionV1,
    ReviewGoalV1,
    ReviewTotalV1,
    ScenarioParametersV1,
    ScenarioSummaryV1,
    ScenarioV1,
)
from app.schemas.v1 import MoneyV1, ProfileV1
from app.services.accounts import NotFoundError, today_utc

_KEY_RE = re.compile(r"^[A-Za-z0-9_.:\-]{8,128}$")


class ConflictError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class ValidationProblem(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _canonical(data: Any) -> str:
    return json.dumps(data, sort_keys=True, separators=(",", ":"), default=str)


def _sha(data: Any) -> str:
    return hashlib.sha256(_canonical(data).encode()).hexdigest()


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def _period(value: str) -> date:
    year, month = value.split("-")
    return date(int(year), int(month), 1)


def _amount(value: Decimal, currency: str) -> AmountV1:
    return AmountV1(amount=Decimal(value).quantize(Decimal("0.01")), currency=currency)


@dataclass(frozen=True)
class PlanningService:
    engine: Engine
    profiles: ProfileRepository
    goals: GoalRepository
    plans: PlanVersionRepository
    scenarios: ScenarioRepository
    progress: ProgressRepository
    idempotency: IdempotencyRepository
    audit: AuditRepository

    # ── Entradas ───────────────────────────────────────────────────────────────

    def _snapshot(self, user: UserRecord, as_of: date) -> PlanSnapshotV1:
        stored = self.profiles.get(user.id)
        if stored is None:
            raise ConflictError("profile_required", "Create a profile before calculating a plan.")
        profile = ProfileV1.model_validate(stored["data"])
        # Snapshot mínimo: sin nombres de activos, deudas o compromisos, país ni tolerancia al riesgo.
        minimal = profile.model_copy(
            update={
                "country": None,
                "risk_tolerance": "medium",
                "assets": [a.model_copy(update={"name": f"asset-{i + 1}"}) for i, a in enumerate(profile.assets)],
                "liabilities": [d.model_copy(update={"name": f"debt-{i + 1}"}) for i, d in enumerate(profile.liabilities)],
                "commitments": [c.model_copy(update={"name": f"commitment-{i + 1}"}) for i, c in enumerate(profile.commitments)],
            }
        )
        profile_updated_at = _aware(stored["updated_at"])
        with self.engine.connect() as conn:
            contributions = goal_contributions(conn, user.id)
        goal_rows = self.goals.list(user.id)
        goal_snaps = []
        for g in goal_rows:
            counted = sum(
                (
                    c["amount"]
                    for c in contributions
                    if c["goal_id"] == g["id"] and _aware(c["recorded_at"]) > _aware(g["saved_as_of"])
                ),
                Decimal("0"),
            )
            goal_snaps.append(
                GoalSnapshotV1(
                    goal_id=g["id"],
                    name=g["name"],
                    target=MoneyV1(amount=g["target_amount"], currency=g["currency"]),
                    saved_declared=MoneyV1(amount=g["saved_amount"], currency=g["currency"]),
                    contributions_since_declared=MoneyV1(amount=counted, currency=g["currency"]),
                    priority=g["priority"],
                    target_date=g["target_date"],
                    horizon_months=g["horizon_months"],
                )
            )
        unreconciled: dict[str, Decimal] = {}
        for c in contributions:
            if c["source"] == "monthly_surplus" and _aware(c["recorded_at"]) > profile_updated_at:
                unreconciled[c["currency"]] = unreconciled.get(c["currency"], Decimal("0")) + c["amount"]
        return PlanSnapshotV1(
            as_of=as_of,
            profile=minimal,
            goals=goal_snaps,
            unreconciled_contributions=[MoneyV1(amount=v, currency=k) for k, v in sorted(unreconciled.items())],
        )

    @staticmethod
    def _fingerprint(snapshot: PlanSnapshotV1) -> str:
        data = snapshot.model_dump(mode="json", exclude={"as_of", "scenario"})
        return _sha(data)

    @staticmethod
    def _planning_profile(snapshot: PlanSnapshotV1) -> dict[str, Any]:
        from app.finance.adapters import planning_profile_from_v1

        profile = snapshot.profile.model_dump(mode="json")
        for i, m in enumerate(snapshot.unreconciled_contributions):
            profile["assets"].append(
                {"name": f"recorded-contributions-{i + 1}", "category": "cash", "liquidity": "high", "value": m.model_dump(mode="json")}
            )
        goal_rows = [
            {
                "id": g.goal_id,
                "name": g.name,
                "currency": g.target.currency,
                "target_amount": g.target.amount,
                "saved_amount": g.saved_declared.amount + g.contributions_since_declared.amount,
                "priority": g.priority,
                "target_date": g.target_date,
                "horizon_months": g.horizon_months,
            }
            for g in snapshot.goals
        ]
        planning = planning_profile_from_v1(profile, goal_rows)
        for item, row in zip(planning["goals"], goal_rows):
            item["goal_id"] = row["id"]
        return planning

    @classmethod
    def compute(cls, snapshot: PlanSnapshotV1) -> PlanResultV1:
        """Cálculo puro a partir del snapshot: es lo que permite reproducir planes históricos."""
        domain = snapshot_from_profile(cls._planning_profile(snapshot), snapshot.as_of)
        if snapshot.scenario is not None:
            domain = apply_scenario(
                domain,
                Scenario(
                    snapshot.scenario.name,
                    income_change=snapshot.scenario.income_change,
                    expense_change=snapshot.scenario.expense_change,
                    annual_return=snapshot.scenario.annual_return,
                ),
            )
        plan = build_plan(domain, DEFAULT_POLICY)
        return PlanResultV1.model_validate(plan_to_dict(plan, run_scenarios(domain)))

    # ── Idempotencia ───────────────────────────────────────────────────────────

    def _idempotent(
        self, user: UserRecord, key: str | None, operation: str, payload: Any, create: Callable[[Connection], tuple[str, str]]
    ) -> tuple[str, bool]:
        if key is None:
            raise ValidationProblem("idempotency_key_required", "Send an Idempotency-Key header to create this resource.")
        if not _KEY_RE.match(key):
            raise ValidationProblem("idempotency_key_invalid", "Idempotency-Key must have 8-128 characters: letters, digits, '-', '_', '.', ':'.")
        request_hash = _sha({"operation": operation, "payload": payload})

        def replay(existing: dict[str, Any]) -> tuple[str, bool]:
            if existing["operation"] != operation or existing["request_hash"] != request_hash:
                raise ValidationProblem("idempotency_key_reused", "This Idempotency-Key was already used with a different request.")
            return existing["resource_id"], True

        existing = self.idempotency.find(user.id, key)
        if existing is not None:
            return replay(existing)
        try:
            with self.engine.begin() as conn:
                resource_type, resource_id = create(conn)
                self.idempotency.store(
                    conn, user.id, key, operation=operation, request_hash=request_hash, resource_type=resource_type, resource_id=resource_id
                )
            return resource_id, False
        except IntegrityError:
            existing = self.idempotency.find(user.id, key)
            if existing is not None:
                return replay(existing)
            raise ConflictError("concurrent_update", "Another change was saved at the same time. Retry the request.")

    # ── Planes ─────────────────────────────────────────────────────────────────

    def _plan_v1(self, row: dict[str, Any]) -> PlanV1:
        legacy = row["snapshot_schema_version"] != SNAPSHOT_SCHEMA_VERSION
        return PlanV1(
            id=row["id"],
            version=row["version"],
            status=row["status"],
            source=row["source"],
            source_scenario_id=row["source_scenario_id"],
            as_of=row["as_of"],
            policy_version=row["policy_version"],
            engine_version=row["engine_version"],
            created_at=row["created_at"],
            superseded_at=row["superseded_at"],
            reproducible=not legacy,
            snapshot=None if legacy else PlanSnapshotV1.model_validate(row["inputs"]),
            result=None if legacy else PlanResultV1.model_validate(row["result"]),
        )

    def create_plan(self, user: UserRecord, as_of: date | None, key: str | None, request_id: str | None) -> tuple[PlanV1, bool]:
        requested = {"as_of": as_of.isoformat() if as_of else None}
        effective_as_of = as_of or today_utc()

        def create(conn: Connection) -> tuple[str, str]:
            snapshot = self._snapshot(user, effective_as_of)
            result = self.compute(snapshot)
            as_of = effective_as_of
            plan_id = self.plans.create_active(
                conn,
                user.id,
                {
                    "source": "baseline",
                    "source_scenario_id": None,
                    "as_of": as_of,
                    "policy_version": result.policy_version,
                    "engine_version": ENGINE_VERSION,
                    "snapshot_schema_version": SNAPSHOT_SCHEMA_VERSION,
                    "inputs_fingerprint": self._fingerprint(snapshot),
                    "inputs": snapshot.model_dump(mode="json"),
                    "result": result.model_dump(mode="json"),
                },
            )
            return "plan", plan_id

        plan_id, replayed = self._idempotent(user, key, "plan.create", requested, create)
        if not replayed:
            self.audit.record(user_id=user.id, action="plan.create", resource_type="plan", outcome="success", resource_id=plan_id, request_id=request_id)
            log_event("plan_created", request_id=request_id, user_id=user.id, plan_id=plan_id)
        return self.get_plan(user, plan_id), replayed

    def get_plan(self, user: UserRecord, plan_id: str) -> PlanV1:
        row = self.plans.get(user.id, plan_id)
        if row is None:
            raise NotFoundError("plan")
        return self._plan_v1(row)

    def list_plans(self, user: UserRecord, limit: int, cursor: str | None) -> tuple[list[PlanSummaryV1], str | None]:
        rows, next_cursor = self.plans.page(user.id, limit, cursor)
        return [PlanSummaryV1.model_validate(r, from_attributes=False) for r in rows], next_cursor

    def freshness(self, user: UserRecord, row: dict[str, Any]) -> FreshnessV1:
        if row["snapshot_schema_version"] != SNAPSHOT_SCHEMA_VERSION:
            return FreshnessV1(is_stale=True, reasons=["legacy_plan"])
        reasons: list[str] = []
        try:
            current = self._snapshot(user, row["as_of"])
            if self._fingerprint(current) != row["inputs_fingerprint"]:
                reasons.append("inputs_changed")
        except ConflictError:
            reasons.append("inputs_changed")
        if row["policy_version"] != DEFAULT_POLICY.version:
            reasons.append("policy_changed")
        if row["engine_version"] != ENGINE_VERSION:
            reasons.append("engine_changed")
        return FreshnessV1(is_stale=bool(reasons), reasons=reasons)  # type: ignore[arg-type]

    def current_plan(self, user: UserRecord) -> CurrentPlanV1:
        row = self.plans.active(user.id)
        if row is None:
            raise NotFoundError("plan")
        return CurrentPlanV1(plan=self._plan_v1(row), freshness=self.freshness(user, row))

    def reproduce(self, user: UserRecord, plan_id: str) -> ReproductionV1:
        row = self.plans.get(user.id, plan_id)
        if row is None:
            raise NotFoundError("plan")
        if row["snapshot_schema_version"] != SNAPSHOT_SCHEMA_VERSION:
            return ReproductionV1(plan_id=plan_id, reproducible=False, identical=None, reason="Plan created before snapshots were stored.")
        if row["policy_version"] != DEFAULT_POLICY.version or row["engine_version"] != ENGINE_VERSION:
            return ReproductionV1(
                plan_id=plan_id, reproducible=False, identical=None, reason="The current engine or policy version differs from the plan."
            )
        recomputed = self.compute(PlanSnapshotV1.model_validate(row["inputs"]))
        stored = PlanResultV1.model_validate(row["result"])
        return ReproductionV1(
            plan_id=plan_id, reproducible=True, identical=recomputed.model_dump(mode="json") == stored.model_dump(mode="json"), reason=None
        )

    def delete_plan(self, user: UserRecord, plan_id: str, request_id: str | None) -> None:
        outcome = self.plans.delete_superseded(user.id, plan_id)
        if outcome == "not_found":
            raise NotFoundError("plan")
        if outcome == "active":
            raise ConflictError("plan_active", "The current plan cannot be deleted. Create or adopt another version first.")
        self.audit.record(user_id=user.id, action="plan.delete", resource_type="plan", outcome="success", resource_id=plan_id, request_id=request_id)

    # ── Escenarios ─────────────────────────────────────────────────────────────

    def _scenario_v1(self, user: UserRecord, row: dict[str, Any]) -> ScenarioV1:
        base_row = self.plans.get(user.id, row["base_plan_id"])
        result = PlanResultV1.model_validate(row["result"])
        base = PlanResultV1.model_validate(base_row["result"]) if base_row else None
        comparison, goal_comparison = _compare(base, result)
        return ScenarioV1(
            id=row["id"],
            base_plan_id=row["base_plan_id"],
            name=row["name"],
            income_change=Decimal(str(row["income_change"])),
            expense_change=Decimal(str(row["expense_change"])),
            annual_return=Decimal(str(row["annual_return"])),
            status=row["status"],
            adopted_plan_id=row["adopted_plan_id"],
            created_at=row["created_at"],
            adopted_at=row["adopted_at"],
            result=result,
            comparison=comparison,
            goal_comparison=goal_comparison,
        )

    def create_scenario(self, user: UserRecord, payload: dict[str, Any], key: str | None, request_id: str | None) -> tuple[ScenarioV1, bool]:
        base_row = self.plans.get(user.id, payload["base_plan_id"])
        if base_row is None:
            raise NotFoundError("plan")
        if base_row["snapshot_schema_version"] != SNAPSHOT_SCHEMA_VERSION:
            raise ConflictError("plan_not_reproducible", "Scenarios need a plan with stored inputs. Create a new plan first.")
        params = ScenarioParametersV1(
            name=payload["name"],
            income_change=payload["income_change"],
            expense_change=payload["expense_change"],
            annual_return=payload["annual_return"],
        )

        def create(conn: Connection) -> tuple[str, str]:
            snapshot = PlanSnapshotV1.model_validate(base_row["inputs"]).model_copy(update={"scenario": params})
            result = self.compute(snapshot)
            scenario_id = self.scenarios.create(
                conn,
                user.id,
                {
                    "base_plan_id": base_row["id"],
                    "name": params.name,
                    "income_change": params.income_change,
                    "expense_change": params.expense_change,
                    "annual_return": params.annual_return,
                    "result": result.model_dump(mode="json"),
                },
            )
            return "scenario", scenario_id

        scenario_id, replayed = self._idempotent(user, key, "scenario.create", payload, create)
        if not replayed:
            self.audit.record(
                user_id=user.id, action="scenario.create", resource_type="scenario", outcome="success", resource_id=scenario_id, request_id=request_id
            )
        return self.get_scenario(user, scenario_id), replayed

    def get_scenario(self, user: UserRecord, scenario_id: str) -> ScenarioV1:
        row = self.scenarios.get(user.id, scenario_id)
        if row is None:
            raise NotFoundError("scenario")
        return self._scenario_v1(user, row)

    def list_scenarios(self, user: UserRecord, limit: int, cursor: str | None, base_plan_id: str | None) -> tuple[list[ScenarioSummaryV1], str | None]:
        rows, next_cursor = self.scenarios.page(user.id, limit, cursor, base_plan_id)
        return [ScenarioSummaryV1.model_validate(r) for r in rows], next_cursor

    def adopt(self, user: UserRecord, scenario_id: str, key: str | None, request_id: str | None) -> tuple[PlanV1, bool]:
        def create(conn: Connection) -> tuple[str, str]:
            scenario = self.scenarios.get(user.id, scenario_id, conn)
            if scenario is None:
                raise NotFoundError("scenario")
            if scenario["status"] == "adopted":
                raise ConflictError("scenario_already_adopted", "This scenario was already adopted.")
            base = self.plans.get(user.id, scenario["base_plan_id"], conn)
            if base is None or base["status"] != "active":
                raise ConflictError(
                    "plan_superseded", "The plan this scenario was based on is no longer current. Simulate the scenario again on the current plan."
                )
            base_snapshot = PlanSnapshotV1.model_validate(base["inputs"])
            snapshot = base_snapshot.model_copy(
                update={
                    "scenario": ScenarioParametersV1(
                        name=scenario["name"],
                        income_change=Decimal(str(scenario["income_change"])),
                        expense_change=Decimal(str(scenario["expense_change"])),
                        annual_return=Decimal(str(scenario["annual_return"])),
                    )
                }
            )
            result = PlanResultV1.model_validate(scenario["result"])
            plan_id = self.plans.create_active(
                conn,
                user.id,
                {
                    "source": "scenario",
                    "source_scenario_id": scenario_id,
                    "as_of": base["as_of"],
                    "policy_version": result.policy_version,
                    "engine_version": ENGINE_VERSION,
                    "snapshot_schema_version": SNAPSHOT_SCHEMA_VERSION,
                    # La huella sigue siendo la de las entradas reales: el escenario no cambia el perfil.
                    "inputs_fingerprint": base["inputs_fingerprint"],
                    "inputs": snapshot.model_dump(mode="json"),
                    "result": result.model_dump(mode="json"),
                },
            )
            if not self.scenarios.mark_adopted(conn, user.id, scenario_id, plan_id):
                raise ConflictError("scenario_already_adopted", "This scenario was already adopted.")
            return "plan", plan_id

        plan_id, replayed = self._idempotent(user, key, "scenario.adopt", {"scenario_id": scenario_id}, create)
        if not replayed:
            self.audit.record(user_id=user.id, action="scenario.adopt", resource_type="plan", outcome="success", resource_id=plan_id, request_id=request_id)
            log_event("scenario_adopted", request_id=request_id, user_id=user.id, plan_id=plan_id, scenario_id=scenario_id)
        return self.get_plan(user, plan_id), replayed

    def delete_scenario(self, user: UserRecord, scenario_id: str) -> None:
        outcome = self.scenarios.delete_simulated(user.id, scenario_id)
        if outcome == "not_found":
            raise NotFoundError("scenario")
        if outcome == "adopted":
            raise ConflictError("scenario_adopted", "An adopted scenario is part of the plan history and cannot be deleted.")

    # ── Avances y revisión ─────────────────────────────────────────────────────

    @staticmethod
    def _entry_v1(row: dict[str, Any]) -> ProgressEntryV1:
        return ProgressEntryV1(
            id=row["id"],
            goal_id=row["goal_id"],
            period=row["period"].strftime("%Y-%m"),
            amount=MoneyV1(amount=row["amount"], currency=row["currency"]),
            source=row["source"],
            recorded_at=row["recorded_at"],
        )

    def record_progress(self, user: UserRecord, payload: dict[str, Any], key: str | None, request_id: str | None) -> tuple[ProgressEntryV1, bool]:
        goal = self.goals.get(user.id, payload["goal_id"])
        if goal is None:
            raise NotFoundError("goal")
        amount = payload["amount"]
        if amount["currency"] != goal["currency"]:
            raise ValidationProblem("currency_mismatch", f"Progress for this goal must be recorded in {goal['currency']}.")
        period = _period(payload["period"])
        today = today_utc()
        if period > date(today.year, today.month, 1):
            raise ValidationProblem("future_period", "Progress cannot be recorded for a future month.")

        def create(conn: Connection) -> tuple[str, str]:
            entry_id = self.progress.create(
                conn,
                user.id,
                {
                    "goal_id": goal["id"],
                    "period": period,
                    "amount": Decimal(str(amount["amount"])),
                    "currency": amount["currency"],
                    "source": payload["source"],
                },
            )
            return "progress", entry_id

        entry_id, replayed = self._idempotent(user, key, "progress.create", payload, create)
        if not replayed:
            self.audit.record(
                user_id=user.id, action="progress.create", resource_type="progress", outcome="success", resource_id=entry_id, request_id=request_id
            )
        row = self.progress.get(user.id, entry_id)
        if row is None:
            raise NotFoundError("progress")
        return self._entry_v1(row), replayed

    def list_progress(
        self, user: UserRecord, limit: int, cursor: str | None, goal_id: str | None, period: str | None
    ) -> tuple[list[ProgressEntryV1], str | None]:
        rows, next_cursor = self.progress.page(user.id, limit, cursor, goal_id, _period(period) if period else None)
        return [self._entry_v1(r) for r in rows], next_cursor

    def delete_progress(self, user: UserRecord, entry_id: str, request_id: str | None) -> None:
        if not self.progress.delete(user.id, entry_id):
            raise NotFoundError("progress")
        self.audit.record(user_id=user.id, action="progress.delete", resource_type="progress", outcome="success", resource_id=entry_id, request_id=request_id)

    def review(self, user: UserRecord, period: str) -> MonthlyReviewV1:
        row = self.plans.active(user.id)
        if row is None:
            raise NotFoundError("plan")
        plan = self._plan_v1(row)
        if plan.result is None:
            raise ConflictError("plan_not_reproducible", "Create a new plan to review monthly progress.")
        entries = self.progress.for_period(user.id, _period(period))
        recorded: dict[str, Decimal] = {}
        for e in entries:
            recorded[e["goal_id"]] = recorded.get(e["goal_id"], Decimal("0")) + e["amount"]
        goals_out: list[ReviewGoalV1] = []
        planned_ids = set()
        for g in plan.result.goals:
            if g.goal_id is None:
                continue
            planned_ids.add(g.goal_id)
            planned = g.monthly_allocation.amount
            got = recorded.get(g.goal_id, Decimal("0"))
            if planned > 0:
                status = "met" if got >= planned else ("partial" if got > 0 else "not_recorded")
            else:
                status = "extra" if got > 0 else "not_planned"
            goals_out.append(
                ReviewGoalV1(
                    goal_id=g.goal_id,
                    goal_name=g.goal_name,
                    currency=g.currency,
                    planned=_amount(planned, g.currency),
                    recorded=_amount(got, g.currency),
                    difference=_amount(got - planned, g.currency),
                    status=status,
                )
            )
        for goal in self.goals.list(user.id):
            if goal["id"] in planned_ids:
                continue
            got = recorded.get(goal["id"], Decimal("0"))
            goals_out.append(
                ReviewGoalV1(
                    goal_id=goal["id"],
                    goal_name=goal["name"],
                    currency=goal["currency"],
                    planned=_amount(Decimal("0"), goal["currency"]),
                    recorded=_amount(got, goal["currency"]),
                    difference=_amount(got, goal["currency"]),
                    status="not_in_plan",
                )
            )
        totals: dict[str, list[Decimal]] = {}
        for g in goals_out:
            t = totals.setdefault(g.currency, [Decimal("0"), Decimal("0")])
            t[0] += g.planned.amount
            t[1] += g.recorded.amount
        return MonthlyReviewV1(
            period=period,
            plan_id=plan.id,
            plan_version=plan.version,
            freshness=self.freshness(user, row),
            goals=goals_out,
            totals=[
                ReviewTotalV1(currency=c, planned=_amount(p, c), recorded=_amount(r, c), difference=_amount(r - p, c))
                for c, (p, r) in sorted(totals.items())
            ],
        )


def _compare(base: PlanResultV1 | None, scenario: PlanResultV1) -> tuple[list[ComparisonBudgetV1], list[ComparisonGoalV1]]:
    if base is None:
        return [], []
    budgets = []
    base_budgets = {b.currency: b for b in base.budgets}
    for b in scenario.budgets:
        bb = base_budgets.get(b.currency)
        if bb is None:
            continue
        budgets.append(
            ComparisonBudgetV1(
                currency=b.currency,
                base_monthly_surplus=bb.monthly.surplus,
                scenario_monthly_surplus=b.monthly.surplus,
                base_goal_contributions=bb.monthly.allocations.goals,
                scenario_goal_contributions=b.monthly.allocations.goals,
                goal_contributions_change=_amount(b.monthly.allocations.goals.amount - bb.monthly.allocations.goals.amount, b.currency),
            )
        )
    base_goals = {g.goal_id: g for g in base.goals}
    goals = []
    for g in scenario.goals:
        bg = base_goals.get(g.goal_id)
        goals.append(
            ComparisonGoalV1(
                goal_id=g.goal_id,
                goal_name=g.goal_name,
                base_status=bg.status if bg else None,
                scenario_status=g.status,
                base_monthly_allocation=bg.monthly_allocation if bg else None,
                scenario_monthly_allocation=g.monthly_allocation,
                base_months_to_goal=bg.months_to_goal if bg else None,
                scenario_months_to_goal=g.months_to_goal,
            )
        )
    return budgets, goals
