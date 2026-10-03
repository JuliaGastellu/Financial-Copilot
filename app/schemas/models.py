"""Contratos internos del motor de recomendaciones y de las rutas de operación.

Los contratos públicos de cuentas, perfil, metas y planes están en `app/schemas/v1.py`.
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class Citation(BaseModel):
    doc_id: str
    chunk_id: str | None = None
    title: str | None = None
    source: str | None = None


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


class ReadyCheck(BaseModel):
    status: Literal["ready", "degraded"]
    checks: dict[str, str]


class HealthResponse(BaseModel):
    status: Literal["ok"] = "ok"
