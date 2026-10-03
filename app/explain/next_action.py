"""Próxima acción del plan: la misma regla de selección que usa la aplicación web."""
from __future__ import annotations

from decimal import Decimal

from app.schemas.plans_v1 import PlanResultV1


def next_action_kind(result: PlanResultV1) -> str:
    if any(b.monthly.surplus.amount < 0 for b in result.budgets):
        return "close_deficit"
    base = next((b for b in result.budgets if b.currency == result.base_currency), None)
    if base is None:
        return "review_data"
    a = base.monthly.allocations
    if a.emergency_reserve.amount > 0:
        return "fund_reserve"
    if a.high_apr_debt.amount > 0:
        return "pay_debt"
    if a.goals.amount > 0:
        return "fund_goals"
    if base.monthly.unassigned.amount > Decimal(0):
        return "assign_surplus"
    return "review_data"
