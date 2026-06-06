from __future__ import annotations

from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, Field


class MoneyAmount(BaseModel):
    amount: float = Field(ge=0)
    currency: str = Field(default="USD", min_length=3, max_length=3)


class Cashflow(BaseModel):
    monthly_income: float = Field(ge=0, description="Total net monthly income.")
    monthly_expenses: float = Field(ge=0, description="Total monthly expenses.")


class Asset(BaseModel):
    name: str = Field(min_length=1)
    category: Literal["cash", "equity", "bond", "real_estate", "retirement", "crypto", "other"] = "other"
    value: float = Field(ge=0)
    liquidity: Literal["high", "medium", "low"] = "medium"


class Liability(BaseModel):
    name: str = Field(min_length=1)
    balance: float = Field(ge=0)
    apr: float | None = Field(default=None, ge=0, le=100, description="Annual percentage rate (0–100).")
    minimum_payment: float | None = Field(default=None, ge=0)


class Goal(BaseModel):
    name: str = Field(min_length=1)
    target_amount: float = Field(ge=0)
    current_amount: float = Field(default=0.0, ge=0, description="Current amount already saved toward the goal.")
    target_date: date | None = None
    horizon_months: int | None = Field(default=None, ge=1)
    priority: Literal["low", "medium", "high"] = "medium"


class FinancialProfile(BaseModel):
    user_id: str = Field(min_length=1)
    country: str | None = None
    risk_tolerance: Literal["low", "medium", "high"] = "medium"
    cashflow: Cashflow
    assets: list[Asset] = Field(default_factory=list)
    liabilities: list[Liability] = Field(default_factory=list)
    goals: list[Goal] = Field(default_factory=list)
    preferences: dict[str, Any] = Field(default_factory=dict)


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
    confidence: float = Field(ge=0, le=1)
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


class RecommendationResponse(BaseModel):
    metrics: dict[str, Any]
    recommendations: list[RecommendationItem]
    mode: Literal["llm", "offline"]
    decision_context: dict[str, Any]


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
