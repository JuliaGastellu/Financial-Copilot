"""Contratos v1. La identidad nunca viaja en la URL ni en el cuerpo: sale del token.

Los modelos de entrada rechazan campos desconocidos (`extra="forbid"`), de modo que un
`user_id` u `owner` agregado al cuerpo produce 422 en lugar de ignorarse.
"""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Any, Literal

from pydantic import AfterValidator, BaseModel, BeforeValidator, ConfigDict, Field, StringConstraints, model_validator


def _upper(value: Any) -> Any:
    return value.strip().upper() if isinstance(value, str) else value


CurrencyCode = Annotated[str, BeforeValidator(_upper), StringConstraints(pattern=r"^[A-Z]{3}$")]
# Acoto importes para mantener exactitud en centavos y limitar abuso; rechazo NaN e infinitos.
AmountValue = Annotated[
    Decimal,
    Field(ge=0, le=Decimal("1000000000000"), max_digits=20, decimal_places=2, allow_inf_nan=False),
    AfterValidator(lambda d: d.quantize(Decimal("0.01"))),
]
Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class MoneyV1(StrictModel):
    amount: AmountValue
    currency: CurrencyCode


class CashflowV1(StrictModel):
    currency: CurrencyCode
    monthly_income: AmountValue
    monthly_expenses: AmountValue
    minimum_payments_included_in_expenses: bool | None = None


class AssetV1(StrictModel):
    name: Name
    category: Literal["cash", "equity", "bond", "real_estate", "retirement", "crypto", "other"] = "other"
    liquidity: Literal["high", "medium", "low"]
    value: MoneyV1


class LiabilityV1(StrictModel):
    name: Name
    balance: MoneyV1
    apr_percent: Decimal | None = Field(default=None, ge=0, le=100, allow_inf_nan=False)
    minimum_payment: MoneyV1 | None = None

    @model_validator(mode="after")
    def _same_currency(self) -> LiabilityV1:
        if self.minimum_payment is not None and self.minimum_payment.currency != self.balance.currency:
            raise ValueError("minimum_payment must use the balance currency.")
        return self


class CommitmentV1(StrictModel):
    name: Name
    kind: Literal["monthly", "reserved_balance"]
    amount: MoneyV1


class ProfileV1(StrictModel):
    currency: CurrencyCode
    country: Annotated[str, StringConstraints(pattern=r"^[A-Z]{2}$")] | None = None
    risk_tolerance: Literal["low", "medium", "high"] = "medium"
    cashflows: list[CashflowV1] = Field(min_length=1, max_length=5)
    assets: list[AssetV1] = Field(default_factory=list, max_length=100)
    liabilities: list[LiabilityV1] = Field(default_factory=list, max_length=100)
    commitments: list[CommitmentV1] = Field(default_factory=list, max_length=100)
    emergency_reserve_months: Decimal | None = Field(default=None, ge=0, le=24, allow_inf_nan=False)

    @model_validator(mode="after")
    def _one_cashflow_per_currency(self) -> ProfileV1:
        currencies = [c.currency for c in self.cashflows]
        if len(currencies) != len(set(currencies)):
            raise ValueError("Use one cashflow per currency.")
        return self


class ProfileResponseV1(BaseModel):
    profile: ProfileV1
    updated_at: datetime


class GoalInputV1(StrictModel):
    name: Name
    target: MoneyV1
    saved: MoneyV1 | None = None
    priority: Literal["low", "medium", "high"] = "medium"
    target_date: date | None = None
    horizon_months: int | None = Field(default=None, ge=1, le=600)

    @model_validator(mode="after")
    def _consistent(self) -> GoalInputV1:
        if self.saved is not None and self.saved.currency != self.target.currency:
            raise ValueError("saved must use the target currency.")
        return self


class GoalV1(BaseModel):
    id: str
    name: str
    target: MoneyV1
    saved: MoneyV1
    priority: Literal["low", "medium", "high"]
    target_date: date | None
    horizon_months: int | None
    created_at: datetime
    updated_at: datetime


class PlanRequestV1(StrictModel):
    as_of: date | None = Field(default=None, description="Fecha del cálculo; por defecto, hoy (UTC).")


class PlanSummaryV1(BaseModel):
    id: str
    as_of: date
    policy_version: str
    created_at: datetime


class PlanRecordV1(PlanSummaryV1):
    plan: dict[str, Any]


class MeV1(BaseModel):
    user_id: str
    created_at: datetime


class DeletionResultV1(BaseModel):
    receipt_id: str
    deleted_at: str
    evidence: dict[str, Any]


class KnowledgeQueryV1(StrictModel):
    query: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1000)]
    top_k: int | None = Field(default=None, ge=1, le=10)


class CitationV1(BaseModel):
    doc_id: str
    chunk_id: str | None = None
    title: str | None = None
    source: str | None = None


class KnowledgeAnswerV1(BaseModel):
    answer: str
    citations: list[CitationV1]
    corpus: Literal["public"] = "public"
    mode: Literal["offline"] = "offline"
