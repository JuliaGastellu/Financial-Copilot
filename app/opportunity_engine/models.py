from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, HttpUrl


class ExpectedReturnRange(BaseModel):
    min_annual: float = Field(description="Expreso el retorno anual mínimo ilustrativo como decimal: 0,05 representa 5%.")
    max_annual: float = Field(description="Expreso el retorno anual máximo ilustrativo como decimal: 0,08 representa 8%.")


class InvestmentHorizon(BaseModel):
    min_months: int = Field(ge=1)
    max_months: int = Field(ge=1)


class InvestmentOpportunity(BaseModel):
    instrument_id: str = Field(min_length=1)
    instrument_name: str = Field(min_length=1)
    asset_class: Literal["cash_equivalent", "bond", "equity", "retirement", "real_estate", "crypto", "other"]
    market_country: str = Field(min_length=2, max_length=2, description="Identifico el país con su código ISO 3166-1 de dos letras.")
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

