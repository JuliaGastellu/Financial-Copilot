"""Contratos tipados de planes, escenarios, avances y revisión mensual.

Guardo el snapshot y el resultado de cada plan como JSON en la base, pero siempre los
valido contra estos modelos al escribir y al leer: no acepto estructuras libres.
"""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Generic, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

from app.schemas.v1 import CurrencyCode, MoneyV1, ProfileV1, StrictModel

SNAPSHOT_SCHEMA_VERSION = 1


class Closed(BaseModel):
    """Modelo de salida cerrado: un campo inesperado es un error de programación."""

    model_config = ConfigDict(extra="forbid")


class AmountV1(Closed):
    """Importe de resultado; puede ser negativo (por ejemplo, un déficit)."""

    amount: Decimal
    currency: CurrencyCode


# ── Snapshot de entradas ───────────────────────────────────────────────────────


class GoalSnapshotV1(Closed):
    goal_id: str
    name: str
    target: MoneyV1
    saved_declared: MoneyV1
    contributions_since_declared: MoneyV1
    priority: Literal["low", "medium", "high"]
    target_date: date | None
    horizon_months: int | None


class ScenarioParametersV1(Closed):
    name: str
    income_change: Decimal
    expense_change: Decimal
    annual_return: Decimal


class PlanSnapshotV1(Closed):
    """Entradas mínimas para reproducir un plan. Omito nombres de activos, país y tolerancia al riesgo."""

    schema_version: Literal[1] = SNAPSHOT_SCHEMA_VERSION
    as_of: date
    profile: ProfileV1
    goals: list[GoalSnapshotV1]
    # Aportes salidos del excedente que todavía no figuran en los saldos declarados del perfil.
    unreconciled_contributions: list[MoneyV1]
    scenario: ScenarioParametersV1 | None = None


# ── Resultado ──────────────────────────────────────────────────────────────────


class MonthlyAllocationsV1(Closed):
    emergency_reserve: AmountV1
    high_apr_debt: AmountV1
    goals: AmountV1


class MonthlyBudgetV1(Closed):
    income: AmountV1
    expenses: AmountV1
    minimum_payments_total: AmountV1
    minimum_payments_added_to_outflow: AmountV1
    commitments: AmountV1
    outflow: AmountV1
    surplus: AmountV1
    allocations: MonthlyAllocationsV1
    allocated_total: AmountV1
    unassigned: AmountV1


class StockAllocationsV1(Closed):
    high_apr_debt: AmountV1
    goals: AmountV1


class CurrentBalancesV1(Closed):
    liquid: AmountV1
    not_counted_as_available: AmountV1
    reserved_commitments: AmountV1
    goal_savings: AmountV1
    reserve_target: AmountV1
    reserve_held: AmountV1
    reserve_gap: AmountV1
    free_after_reserve: AmountV1
    allocations: StockAllocationsV1
    allocated_total: AmountV1
    unassigned: AmountV1


class DebtSummaryV1(Closed):
    total: AmountV1
    high_apr: AmountV1
    high_apr_count: int


class CurrencyBudgetV1(Closed):
    currency: CurrencyCode
    monthly: MonthlyBudgetV1
    current_balances: CurrentBalancesV1
    debt: DebtSummaryV1


GoalStatus = Literal["achieved", "funded_now", "on_track", "underfunded", "overdue", "no_deadline"]


class GoalAllocationV1(Closed):
    goal_id: str | None
    goal_name: str
    currency: CurrencyCode
    priority: Literal["low", "medium", "high"]
    status: GoalStatus
    target: AmountV1
    saved: AmountV1
    remaining: AmountV1
    one_time_allocation: AmountV1
    monthly_allocation: AmountV1
    required_monthly: AmountV1 | None
    shortfall_monthly: AmountV1 | None
    months_left: int | None
    deadline_source: Literal["target_date", "horizon_months"] | None
    months_to_goal: int | None


class ConstraintV1(Closed):
    constraint_id: str
    severity: Literal["low", "medium", "high"]
    currency: CurrencyCode | None
    message: str
    evidence: dict[str, str]
    effect: str
    blocks_new_investment: bool


class ScenarioBudgetV1(Closed):
    currency: CurrencyCode
    monthly_surplus: AmountV1
    emergency_reserve: AmountV1
    high_apr_debt: AmountV1
    goals: AmountV1
    unassigned: AmountV1


class ScenarioGoalV1(Closed):
    goal_id: str | None
    goal_name: str
    currency: CurrencyCode
    status: GoalStatus
    monthly_allocation: AmountV1
    months_to_goal: int | None
    balance_at_deadline: AmountV1 | None


class ScenarioOutcomeV1(Closed):
    name: str
    income_change: Decimal
    expense_change: Decimal
    annual_return: Decimal
    budgets: list[ScenarioBudgetV1]
    goals: list[ScenarioGoalV1]


class PlanResultV1(Closed):
    as_of: date
    policy_version: str
    base_currency: CurrencyCode
    reserve_months: Decimal
    budgets: list[CurrencyBudgetV1]
    goals: list[GoalAllocationV1]
    constraints: list[ConstraintV1]
    assumptions: list[str]
    missing_data: list[str]
    scenarios: list[ScenarioOutcomeV1]


# ── Recursos ───────────────────────────────────────────────────────────────────


class PlanV1(BaseModel):
    id: str
    version: int
    status: Literal["active", "superseded"]
    source: Literal["baseline", "scenario", "legacy"]
    source_scenario_id: str | None
    as_of: date
    policy_version: str
    engine_version: str
    created_at: datetime
    superseded_at: datetime | None
    reproducible: bool
    snapshot: PlanSnapshotV1 | None
    result: PlanResultV1 | None


class PlanSummaryV1(BaseModel):
    id: str
    version: int
    status: Literal["active", "superseded"]
    source: Literal["baseline", "scenario", "legacy"]
    as_of: date
    policy_version: str
    engine_version: str
    created_at: datetime


class FreshnessV1(BaseModel):
    is_stale: bool
    reasons: list[Literal["inputs_changed", "policy_changed", "engine_changed", "legacy_plan"]]


class CurrentPlanV1(BaseModel):
    plan: PlanV1
    freshness: FreshnessV1


class ReproductionV1(BaseModel):
    plan_id: str
    reproducible: bool
    identical: bool | None
    reason: str | None


class PlanCreateV1(StrictModel):
    as_of: date | None = Field(default=None, description="Fecha del cálculo; por defecto, hoy (UTC).")


Rate = Annotated[Decimal, Field(max_digits=6, decimal_places=4, allow_inf_nan=False)]


class ScenarioCreateV1(StrictModel):
    base_plan_id: str
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)]
    income_change: Rate = Field(default=Decimal("0"), ge=Decimal("-1"), le=Decimal("5"), description="Fracción: -0.2 es una caída de 20%.")
    expense_change: Rate = Field(default=Decimal("0"), ge=Decimal("-1"), le=Decimal("5"))
    annual_return: Rate = Field(default=Decimal("0"), gt=Decimal("-1"), le=Decimal("1"))


class ComparisonBudgetV1(BaseModel):
    currency: str
    base_monthly_surplus: AmountV1
    scenario_monthly_surplus: AmountV1
    base_goal_contributions: AmountV1
    scenario_goal_contributions: AmountV1
    goal_contributions_change: AmountV1


class ComparisonGoalV1(BaseModel):
    goal_id: str | None
    goal_name: str
    base_status: GoalStatus | None
    scenario_status: GoalStatus | None
    base_monthly_allocation: AmountV1 | None
    scenario_monthly_allocation: AmountV1 | None
    base_months_to_goal: int | None
    scenario_months_to_goal: int | None


class ScenarioV1(BaseModel):
    id: str
    base_plan_id: str
    name: str
    income_change: Decimal
    expense_change: Decimal
    annual_return: Decimal
    status: Literal["simulated", "adopted"]
    adopted_plan_id: str | None
    created_at: datetime
    adopted_at: datetime | None
    result: PlanResultV1
    comparison: list[ComparisonBudgetV1]
    goal_comparison: list[ComparisonGoalV1]


class ScenarioSummaryV1(BaseModel):
    id: str
    base_plan_id: str
    name: str
    status: Literal["simulated", "adopted"]
    created_at: datetime


class ProgressCreateV1(StrictModel):
    goal_id: str
    period: Annotated[str, StringConstraints(pattern=r"^\d{4}-(0[1-9]|1[0-2])$")]
    amount: MoneyV1
    source: Literal["monthly_surplus", "existing_balance"] = Field(
        default="monthly_surplus",
        description="monthly_surplus: dinero nuevo del excedente; existing_balance: dinero que ya estaba en saldos declarados.",
    )

    @field_validator("amount")
    @classmethod
    def _positive(cls, value: MoneyV1) -> MoneyV1:
        if value.amount <= 0:
            raise ValueError("amount must be greater than zero.")
        return value


class ProgressEntryV1(BaseModel):
    id: str
    goal_id: str
    period: str
    amount: MoneyV1
    source: Literal["monthly_surplus", "existing_balance"]
    recorded_at: datetime


ReviewStatus = Literal["met", "partial", "not_recorded", "not_planned", "extra", "not_in_plan"]


class ReviewGoalV1(BaseModel):
    goal_id: str
    goal_name: str
    currency: str
    planned: AmountV1
    recorded: AmountV1
    difference: AmountV1
    status: ReviewStatus


class ReviewTotalV1(BaseModel):
    currency: str
    planned: AmountV1
    recorded: AmountV1
    difference: AmountV1


class MonthlyReviewV1(BaseModel):
    period: str
    plan_id: str
    plan_version: int
    freshness: FreshnessV1
    goals: list[ReviewGoalV1]
    totals: list[ReviewTotalV1]


T = TypeVar("T")


class Page(BaseModel, Generic[T]):
    items: list[T]
    next_cursor: str | None
