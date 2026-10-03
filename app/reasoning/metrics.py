from __future__ import annotations

from datetime import date
from typing import Any

from app.finance import plan_for_profile
from app.finance.planning import FinancialPlan
from app.finance.serialization import plan_metrics


def compute_profile_metrics(
    profile: dict[str, Any], *, as_of: date | None = None, plan: FinancialPlan | None = None
) -> dict[str, Any]:
    """Calculo métricas de la moneda base a partir del plan del dominio financiero."""
    plan = plan or plan_for_profile(profile, as_of or date.today())
    return plan_metrics(plan)
