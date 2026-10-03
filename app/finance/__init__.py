"""Dominio financiero puro: importes, perfil, políticas y plan. No depende de red ni de almacenamiento."""
from __future__ import annotations

from datetime import date
from typing import Any

from app.finance.adapters import snapshot_from_profile
from app.finance.planning import FinancialPlan, build_plan
from app.finance.policy import DEFAULT_POLICY, PlanningPolicy

# Versión del motor de cálculo. La cambio cuando cambia el resultado para las mismas entradas.
ENGINE_VERSION = "1.0.0"


def plan_for_profile(profile: dict[str, Any], as_of: date, policy: PlanningPolicy = DEFAULT_POLICY) -> FinancialPlan:
    return build_plan(snapshot_from_profile(profile, as_of), policy)
