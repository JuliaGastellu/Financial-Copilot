from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class OpportunitySummary(BaseModel):
    instrument_id: str
    instrument_name: str
    risk_level: str
    liquidity_level: str
    minimum_capital: float
    market_country: str
    currency: str
    investment_horizon_months: dict[str, int]


class OpportunityRejection(BaseModel):
    instrument_id: str
    instrument_name: str
    reasons: list[str] = Field(default_factory=list)


class ScoringBreakdown(BaseModel):
    instrument_id: str
    total_score: float = Field(ge=0, le=1)
    risk_score: float = Field(ge=0, le=1)
    liquidity_score: float = Field(ge=0, le=1)
    capital_score: float = Field(ge=0, le=1)
    horizon_alignment_score: float = Field(ge=0, le=1)
    details: dict[str, Any] = Field(default_factory=dict)


class DecisionTrace(BaseModel):
    input_summary: dict[str, Any]
    filters_applied: list[str]
    eligible_opportunities: list[OpportunitySummary]
    rejected_opportunities: list[OpportunityRejection]
    scoring_breakdown: list[ScoringBreakdown]
    selected_option_reason: str
    alternatives_considered: list[dict[str, Any]] = Field(default_factory=list)

