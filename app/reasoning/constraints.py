from __future__ import annotations

from datetime import date
from typing import Any

from app.finance import plan_for_profile
from app.finance.planning import FinancialPlan
from app.finance.serialization import constraint_to_dict


def detect_constraints(
    profile: dict[str, Any],
    metrics: dict[str, Any] | None = None,
    *,
    as_of: date | None = None,
    plan: FinancialPlan | None = None,
) -> list[dict[str, Any]]:
    """Devuelvo las restricciones del plan con su efecto sobre la decisión.

    Mantengo el parámetro `metrics` por compatibilidad; las restricciones salen del plan.
    """
    plan = plan or plan_for_profile(profile, as_of or date.today())
    return [constraint_to_dict(c) for c in plan.constraints]
