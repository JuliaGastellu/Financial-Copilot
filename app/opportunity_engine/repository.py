from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from app.opportunity_engine.models import InvestmentOpportunity


def _default_dataset_path() -> Path:
    return Path(__file__).with_name("opportunities.json")


@dataclass(frozen=True)
class OpportunityRepository:
    dataset_path: Path = _default_dataset_path()

    def load_all(self) -> list[InvestmentOpportunity]:
        raw = json.loads(self.dataset_path.read_text(encoding="utf-8"))
        if not isinstance(raw, list):
            raise ValueError("Opportunity dataset must be a JSON array.")
        return [InvestmentOpportunity.model_validate(item) for item in raw]

    def filter(
        self,
        *,
        market_country: str | None = None,
        currency: str | None = None,
        asset_classes: set[str] | None = None,
    ) -> list[InvestmentOpportunity]:
        items = self.load_all()
        out: list[InvestmentOpportunity] = []
        for op in items:
            if market_country and op.market_country.upper() != market_country.upper():
                continue
            if currency and op.currency.upper() != currency.upper():
                continue
            if asset_classes and op.asset_class not in asset_classes:
                continue
            out.append(op)
        return out

