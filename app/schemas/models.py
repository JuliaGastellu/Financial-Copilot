from __future__ import annotations

from datetime import date
from typing import Annotated, Any, Literal

from pydantic import BaseModel, BeforeValidator, Field, StringConstraints, model_validator


def _upper(value: Any) -> Any:
    return value.strip().upper() if isinstance(value, str) else value


# Código ISO 4217; acepto minúsculas y las normalizo.
CurrencyCode = Annotated[str, BeforeValidator(_upper), StringConstraints(pattern=r"^[A-Z]{3}$")]

# Rechazo NaN e infinitos en todos los importes.
Amount = Annotated[float, Field(ge=0, allow_inf_nan=False)]


class MoneyAmount(BaseModel):
    amount: Amount
    currency: CurrencyCode = "USD"


class Cashflow(BaseModel):
    monthly_income: Amount = Field(description="Registro el ingreso neto mensual total.")
    monthly_expenses: Amount = Field(description="Registro los gastos mensuales totales.")
    currency: CurrencyCode | None = Field(default=None, description="Moneda del flujo; si falta, uso la moneda base del perfil.")
    minimum_payments_included_in_expenses: bool | None = Field(
        default=None,
        description="Indico si los pagos mínimos de deudas en esta moneda ya están en los gastos. Si falta, los sumo a las salidas.",
    )


class AdditionalCashflow(BaseModel):
    currency: CurrencyCode
    monthly_income: Amount = 0.0
    monthly_expenses: Amount = 0.0
    minimum_payments_included_in_expenses: bool | None = None


class Asset(BaseModel):
    name: str = Field(min_length=1)
    category: Literal["cash", "equity", "bond", "real_estate", "retirement", "crypto", "other"] = "other"
    value: Amount
    liquidity: Literal["high", "medium", "low"] = "medium"
    currency: CurrencyCode | None = None


class Liability(BaseModel):
    name: str = Field(min_length=1)
    balance: Amount
    apr: float | None = Field(default=None, ge=0, le=100, allow_inf_nan=False, description="Expreso la tasa anual como porcentaje entre 0 y 100.")
    minimum_payment: Amount | None = None
    currency: CurrencyCode | None = None


class Goal(BaseModel):
    name: str = Field(min_length=1)
    target_amount: Amount
    current_amount: Amount = Field(default=0.0, description="Registro el importe ya ahorrado para la meta.")
    target_date: date | None = None
    horizon_months: int | None = Field(default=None, ge=1, le=600)
    priority: Literal["low", "medium", "high"] = "medium"
    currency: CurrencyCode | None = None


class Commitment(BaseModel):
    name: str = Field(min_length=1)
    amount: Amount
    kind: Literal["monthly", "reserved_balance"] = Field(
        default="monthly",
        description="monthly resta del flujo de cada mes; reserved_balance aparta saldo actual que no está libre.",
    )
    currency: CurrencyCode | None = None


class FinancialProfile(BaseModel):
    user_id: str = Field(min_length=1)
    country: str | None = None
    currency: CurrencyCode | None = Field(default=None, description="Moneda base del perfil. Si falta, uso preferences.currency y después USD.")
    risk_tolerance: Literal["low", "medium", "high"] = "medium"
    cashflow: Cashflow
    additional_cashflows: list[AdditionalCashflow] = Field(default_factory=list)
    assets: list[Asset] = Field(default_factory=list)
    liabilities: list[Liability] = Field(default_factory=list)
    goals: list[Goal] = Field(default_factory=list)
    commitments: list[Commitment] = Field(default_factory=list)
    emergency_reserve_months: float | None = Field(
        default=None, ge=0, le=24, allow_inf_nan=False, description="Meses de salidas que la persona quiere reservar. Si falta, uso la política por defecto."
    )
    preferences: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _one_cashflow_per_currency(self) -> FinancialProfile:
        base = self.currency or _upper((self.preferences or {}).get("currency")) or "USD"
        seen = {self.cashflow.currency or base}
        for extra in self.additional_cashflows:
            if extra.currency in seen:
                raise ValueError(f"Duplicate cashflow for currency {extra.currency}.")
            seen.add(extra.currency)
        return self


class ProfileUpsertRequest(BaseModel):
    profile: FinancialProfile


class ProfileResponse(BaseModel):
    profile: FinancialProfile


class IngestDocumentRequest(BaseModel):
    title: str = Field(min_length=1)
    source: str | None = None
    content: str = Field(min_length=1)
    content_type: Literal["text", "html"] = "text"


class IngestDocumentResponse(BaseModel):
    doc_id: str
    chunks_indexed: int


class QueryRequest(BaseModel):
    user_id: str = Field(min_length=1)
    query: str = Field(min_length=1)
    top_k: int | None = Field(default=None, ge=1, le=20)
    include_recommendations: bool = True


class Citation(BaseModel):
    doc_id: str
    chunk_id: str | None = None
    title: str | None = None
    source: str | None = None


class QueryResponse(BaseModel):
    answer: str
    recommendations: list[dict[str, Any]]
    citations: list[Citation]
    mode: Literal["llm", "offline"]
    fallback_used: bool
    fallback_reason: str | None = None


class RecommendationRequest(BaseModel):
    user_id: str = Field(min_length=1)
    focus: Literal["overview", "debt", "investing", "savings", "goals"] = "overview"


class RecommendationItem(BaseModel):
    title: str
    rationale: str
    actions: list[str]
    risks: list[str] = Field(default_factory=list)
    sources: list[Citation] = Field(default_factory=list)
    opportunity: dict[str, Any] | None = None
    match_reason: str | None = None
    match_score: float | None = Field(default=None, ge=0, le=1)
    score_components: dict[str, float] | None = None
    decision_trace: dict[str, Any] | None = None
    impacted_goals: list[dict[str, Any]] = Field(default_factory=list)
    projected_impact: dict[str, Any] | None = None
    suggested_amount: float | None = Field(default=None, ge=0)
    suggested_currency: str | None = Field(default=None, min_length=3, max_length=3)
    allocation_kind: Literal["simultaneous", "alternative", "informational"] = Field(
        default="informational",
        description="simultaneous suma dentro del presupuesto del plan; alternative excluye a las demás alternativas; informational no asigna dinero.",
    )
    plan_action: Literal["emergency_reserve", "high_apr_debt", "goals"] | None = None
    plan_currency: str | None = None


class RecommendationResponse(BaseModel):
    metrics: dict[str, Any]
    recommendations: list[RecommendationItem]
    mode: Literal["llm", "offline"]
    decision_context: dict[str, Any]


class PlanResponse(BaseModel):
    as_of: str
    policy_version: str
    base_currency: str
    reserve_months: str
    budgets: list[dict[str, Any]]
    goals: list[dict[str, Any]]
    constraints: list[dict[str, Any]]
    assumptions: list[str]
    missing_data: list[str]
    scenarios: list[dict[str, Any]]


class DecisionRecord(BaseModel):
    decision_id: str
    user_id: str
    created_at: str
    recommendations: list[dict[str, Any]]
    decision_context: dict[str, Any]
    mode: str


class ReadyCheck(BaseModel):
    status: Literal["ready", "degraded"]
    checks: dict[str, str]


class HealthResponse(BaseModel):
    status: Literal["ok"] = "ok"
