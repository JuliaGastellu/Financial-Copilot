"""Representación JSON del plan y métricas de compatibilidad.

En el plan expreso importes como {"amount": "<decimal>", "currency": "<ISO>"}.
Las métricas heredadas siguen siendo números para no romper clientes existentes.
"""
from __future__ import annotations

from dataclasses import asdict
from decimal import Decimal
from typing import Any

from app.finance.money import Money
from app.finance.planning import CurrencyBudget, FinancialPlan, GoalPlan, PlanConstraint, ScenarioResult


def _m(value: Money | None) -> dict[str, str] | None:
    return value.to_json() if value is not None else None


def _f(value: Money | Decimal | None) -> float | None:
    if value is None:
        return None
    if isinstance(value, Money):
        return float(value.round().amount)
    return float(value)


def budget_to_dict(b: CurrencyBudget) -> dict[str, Any]:
    return {
        "currency": b.currency,
        "monthly": {
            "income": _m(b.monthly_income),
            "expenses": _m(b.monthly_expenses),
            "minimum_payments_total": _m(b.minimum_payments_total),
            "minimum_payments_added_to_outflow": _m(b.minimum_payments_added),
            "commitments": _m(b.monthly_commitments),
            "outflow": _m(b.monthly_outflow),
            "surplus": _m(b.monthly_surplus),
            "allocations": {
                "emergency_reserve": _m(b.reserve_contribution),
                "high_apr_debt": _m(b.high_apr_debt_payment),
                "goals": _m(b.goal_contributions),
            },
            "allocated_total": _m(b.monthly_allocated),
            "unassigned": _m(b.unassigned_monthly),
        },
        "current_balances": {
            "liquid": _m(b.liquid_balance),
            "not_counted_as_available": _m(b.other_balances),
            "reserved_commitments": _m(b.reserved_balances),
            "goal_savings": _m(b.goal_savings),
            "reserve_target": _m(b.reserve_target),
            "reserve_held": _m(b.reserve_held),
            "reserve_gap": _m(b.reserve_gap),
            "free_after_reserve": _m(b.free_stock),
            "allocations": {
                "high_apr_debt": _m(b.stock_to_high_apr_debt),
                "goals": _m(b.stock_to_goals),
            },
            "allocated_total": _m(b.stock_allocated),
            "unassigned": _m(b.unassigned_stock),
        },
        "debt": {
            "total": _m(b.total_debt),
            "high_apr": _m(b.high_apr_debt),
            "high_apr_count": b.high_apr_debt_count,
        },
    }


def goal_to_dict(g: GoalPlan) -> dict[str, Any]:
    return {
        "goal_name": g.name,
        "currency": g.currency,
        "priority": g.priority,
        "status": g.status,
        "target": _m(g.target),
        "saved": _m(g.saved),
        "remaining": _m(g.remaining),
        "one_time_allocation": _m(g.one_time_allocation),
        "monthly_allocation": _m(g.monthly_allocation),
        "required_monthly": _m(g.required_monthly),
        "shortfall_monthly": _m(g.shortfall_monthly),
        "months_left": g.months_left,
        "deadline_source": g.deadline_source,
        "months_to_goal": g.months_to_goal,
    }


def constraint_to_dict(c: PlanConstraint) -> dict[str, Any]:
    return asdict(c)


def scenario_to_dict(result: ScenarioResult) -> dict[str, Any]:
    s = result.scenario
    return {
        "name": s.name,
        "income_change": format(s.income_change, "f"),
        "expense_change": format(s.expense_change, "f"),
        "annual_return": format(s.annual_return, "f"),
        "budgets": [
            {
                "currency": b.currency,
                "monthly_surplus": _m(b.monthly_surplus),
                "emergency_reserve": _m(b.reserve_contribution),
                "high_apr_debt": _m(b.high_apr_debt_payment),
                "goals": _m(b.goal_contributions),
                "unassigned": _m(b.unassigned_monthly),
            }
            for b in result.plan.budgets
        ],
        "goals": [
            {
                "goal_name": g.name,
                "currency": g.currency,
                "status": g.status,
                "monthly_allocation": _m(g.monthly_allocation),
                "months_to_goal": p.months_to_goal,
                "balance_at_deadline": _m(p.balance_at_deadline),
            }
            for g, p in zip(result.plan.goals, result.projections)
        ],
    }


def plan_to_dict(plan: FinancialPlan, scenarios: list[ScenarioResult] | None = None) -> dict[str, Any]:
    return {
        "as_of": plan.as_of.isoformat(),
        "policy_version": plan.policy_version,
        "base_currency": plan.base_currency,
        "reserve_months": format(plan.reserve_months, "f"),
        "budgets": [budget_to_dict(b) for b in plan.budgets],
        "goals": [goal_to_dict(g) for g in plan.goals],
        "constraints": [constraint_to_dict(c) for c in plan.constraints],
        "assumptions": list(plan.assumptions),
        "missing_data": list(plan.missing_data),
        "scenarios": [scenario_to_dict(s) for s in scenarios or []],
    }


def plan_metrics(plan: FinancialPlan) -> dict[str, Any]:
    """Métricas de la moneda base. Indico la unidad de cada ratio en `metric_units`."""
    b = plan.budget(plan.base_currency)
    assert b is not None
    income = b.monthly_income.amount
    outflow = b.monthly_outflow.amount
    total_assets = b.liquid_balance + b.other_balances
    reserve_base = (b.liquid_balance - b.reserved_balances - b.goal_savings).clamp_non_negative()

    def ratio(num: Decimal, den: Decimal) -> float | None:
        return float((num / den).quantize(Decimal("0.0001"))) if den > 0 else None

    return {
        "currency": b.currency,
        "monthly_income": _f(b.monthly_income),
        "monthly_expenses": _f(b.monthly_expenses),
        "monthly_outflow": _f(b.monthly_outflow),
        "free_cashflow": _f(b.monthly_surplus),
        "savings_rate": ratio(b.monthly_surplus.amount, income) if income > 0 else 0.0,
        "total_assets": _f(total_assets),
        "total_liabilities": _f(b.total_debt),
        "net_worth": _f(total_assets - b.total_debt),
        "liquid_assets": _f(b.liquid_balance),
        "emergency_fund_months": ratio(reserve_base.amount, outflow),
        "debt_service_ratio": ratio(b.minimum_payments_total.amount, income),
        "debt_balance_to_monthly_income": ratio(b.total_debt.amount, income),
        "debt_to_assets_ratio": ratio(b.total_debt.amount, total_assets.amount),
        "high_apr_debt_count": b.high_apr_debt_count,
        "metric_units": {
            "savings_rate": "monthly_surplus / monthly_income",
            "emergency_fund_months": "months of monthly_outflow covered by liquid balances not reserved or saved for goals",
            "debt_service_ratio": "minimum_payments / monthly_income",
            "debt_balance_to_monthly_income": "months of income (debt_balance / monthly_income); informational, no threshold",
            "debt_to_assets_ratio": "debt_balance / total_assets",
        },
    }
