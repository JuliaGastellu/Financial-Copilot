"""Vinculo recomendaciones con el plan: importes, metas afectadas y tipo de asignación.

Solo las acciones del plan llevan importe. Las acciones simultáneas suman, como
máximo, el excedente mensual de su moneda. Las alternativas (por ejemplo, entradas
del catálogo) se excluyen entre sí y no reciben importe sugerido.
"""
from __future__ import annotations

from datetime import date
from typing import Any

from app.finance import plan_for_profile
from app.finance.planning import FinancialPlan, available_capital
from app.finance.serialization import goal_to_dict

PLAN_ACTIONS = ("emergency_reserve", "high_apr_debt", "goals")


def estimate_available_capital(
    profile: dict[str, Any],
    metrics: dict[str, Any] | None = None,
    *,
    as_of: date | None = None,
    plan: FinancialPlan | None = None,
) -> float:
    """Saldo actual libre en la moneda base, después de reserva, compromisos, deuda cara y metas.

    No incluye ingresos futuros. Es la única estimación de capital disponible del proyecto.
    """
    plan = plan or plan_for_profile(profile, as_of or date.today())
    return float(available_capital(plan, plan.base_currency).round().amount)


def _plan_amount(plan: FinancialPlan, action: str, currency: str) -> tuple[float | None, list[dict[str, Any]]]:
    budget = plan.budget(currency)
    if budget is None:
        return None, []
    if action == "emergency_reserve":
        return float(budget.reserve_contribution.round().amount), []
    if action == "high_apr_debt":
        return float(budget.high_apr_debt_payment.round().amount), []
    if action == "goals":
        goals = [goal_to_dict(g) for g in plan.goals if g.currency == currency]
        return float(budget.goal_contributions.round().amount), goals
    return None, []


def attach_plan_amounts(recommendations: list[dict[str, Any]], plan: FinancialPlan) -> None:
    for rec in recommendations:
        if not isinstance(rec, dict):
            continue
        action = rec.get("plan_action")
        rec["suggested_amount"] = None
        rec["suggested_currency"] = None
        rec["impacted_goals"] = []
        rec["projected_impact"] = None
        if action in PLAN_ACTIONS:
            currency = rec.get("plan_currency") or plan.base_currency
            amount, goals = _plan_amount(plan, action, currency)
            rec["allocation_kind"] = "simultaneous"
            if amount is not None and amount > 0:
                rec["suggested_amount"] = amount
                rec["suggested_currency"] = currency
            rec["impacted_goals"] = goals
            rec["projected_impact"] = {
                "explanation": (
                    f"Monthly amount from the joint plan in {currency}. Reserve, high-interest debt and goal "
                    "allocations add up to at most the monthly surplus."
                ),
                "assumptions": list(plan.assumptions),
                "missing_data": list(plan.missing_data),
            }
        elif rec.get("opportunity"):
            rec["allocation_kind"] = "alternative"
        else:
            rec["allocation_kind"] = "informational"
