from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, HttpUrl


class ExpectedReturnRange(BaseModel):
    min_annual: float = Field(description="Minimum expected annual return, expressed as a decimal (for example, 0.05 for 5%).")
    max_annual: float = Field(description="Maximum expected annual return, expressed as a decimal (for example, 0.08 for 8%).")


class InvestmentHorizon(BaseModel):
    min_months: int = Field(ge=1)
    max_months: int = Field(ge=1)


class InvestmentOpportunity(BaseModel):
    instrument_id: str = Field(min_length=1)
    instrument_name: str = Field(min_length=1)
    asset_class: Literal["cash_equivalent", "bond", "equity", "retirement", "real_estate", "crypto", "other"]
    market_country: str = Field(min_length=2, max_length=2, description="ISO 3166-1 alpha-2 country code.")
    currency: str = Field(min_length=3, max_length=3)
    minimum_capital: float = Field(ge=0)
    liquidity_level: Literal["high", "medium", "low"]
    expected_return_range: ExpectedReturnRange
    risk_level: Literal["low", "medium", "high"]
    investment_horizon: InvestmentHorizon
    access_requirements: list[str] = Field(default_factory=list)
    source_name: str = Field(min_length=1)
    source_url: HttpUrl
    last_updated_at: datetime

