"""Hechos autorizados de un plan para explicarlo.

Solo envío al proveedor lo necesario para explicar el reparto: importes del presupuesto, estado
y aportes de cada meta, restricciones y la próxima acción. Reemplazo los nombres de las metas por
etiquetas (meta-1, meta-2) y los restituyo localmente. No envío identificadores de la cuenta,
saldos detallados, deudas por nombre ni texto libre de la persona.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from app.schemas.plans_v1 import PlanResultV1

PRIORITY_ES = {"high": "alta", "medium": "media", "low": "baja"}


@dataclass(frozen=True)
class Fact:
    id: str
    kind: str
    currency: str | None
    amount: Decimal | None = None
    value: str | int | None = None
    goal: str | None = None


@dataclass
class PlanFacts:
    plan_date: str
    base_currency: str
    facts: dict[str, Fact] = field(default_factory=dict)
    goals: list[dict[str, Any]] = field(default_factory=list)
    constraints: list[dict[str, Any]] = field(default_factory=list)
    next_action: str = "review_data"
    labels: dict[str, str] = field(default_factory=dict)  # etiqueta → nombre real (nunca sale del servidor)

    def add(self, kind: str, currency: str | None, *, amount: Decimal | None = None, value: Any = None, goal: str | None = None) -> str:
        fact_id = f"f{len(self.facts) + 1}"
        self.facts[fact_id] = Fact(fact_id, kind, currency, amount, value, goal)
        return fact_id

    def for_provider(self) -> dict[str, Any]:
        """Representación compacta que envío al proveedor."""
        return {
            "plan_date": self.plan_date,
            "base_currency": self.base_currency,
            "next_action": self.next_action,
            "facts": [
                {k: v for k, v in {
                    "id": f.id,
                    "kind": f.kind,
                    "currency": f.currency,
                    "amount": format(f.amount, "f") if f.amount is not None else None,
                    "value": f.value,
                    "goal": f.goal,
                }.items() if v is not None}
                for f in self.facts.values()
            ],
            "goals": self.goals,
            "constraints": self.constraints,
        }


def _dec(m: Any) -> Decimal:
    return Decimal(str(m.amount)).quantize(Decimal("0.01"))


def build_facts(result: PlanResultV1) -> PlanFacts:
    pf = PlanFacts(plan_date=result.as_of.isoformat(), base_currency=result.base_currency)
    base = next((b for b in result.budgets if b.currency == result.base_currency), result.budgets[0] if result.budgets else None)
    for b in result.budgets:
        c = b.currency
        pf.add("monthly_surplus", c, amount=_dec(b.monthly.surplus))
        pf.add("monthly_income", c, amount=_dec(b.monthly.income))
        pf.add("monthly_outflow", c, amount=_dec(b.monthly.outflow))
        pf.add("reserve_contribution", c, amount=_dec(b.monthly.allocations.emergency_reserve))
        pf.add("high_apr_debt_payment", c, amount=_dec(b.monthly.allocations.high_apr_debt))
        pf.add("goal_contributions", c, amount=_dec(b.monthly.allocations.goals))
        pf.add("unassigned_monthly", c, amount=_dec(b.monthly.unassigned))
        pf.add("reserve_target", c, amount=_dec(b.current_balances.reserve_target))
        pf.add("reserve_gap", c, amount=_dec(b.current_balances.reserve_gap))
    pf.add("reserve_months", None, value=str(result.reserve_months))
    for i, g in enumerate(result.goals, start=1):
        label = f"meta-{i}"
        pf.labels[label] = g.goal_name
        entry: dict[str, Any] = {
            "label": label,
            "priority": g.priority,
            "status": g.status,
            "monthly_fact": pf.add("goal_monthly", g.currency, amount=_dec(g.monthly_allocation), goal=label),
            "one_time_fact": pf.add("goal_one_time", g.currency, amount=_dec(g.one_time_allocation), goal=label),
            "remaining_fact": pf.add("goal_remaining", g.currency, amount=_dec(g.remaining), goal=label),
        }
        if g.shortfall_monthly is not None:
            entry["shortfall_fact"] = pf.add("goal_shortfall", g.currency, amount=_dec(g.shortfall_monthly), goal=label)
        if g.months_to_goal is not None:
            entry["months_fact"] = pf.add("goal_months_to_goal", None, value=g.months_to_goal, goal=label)
        if g.months_left is not None:
            entry["deadline_fact"] = pf.add("goal_months_left", None, value=g.months_left, goal=label)
        pf.goals.append(entry)
    for c in result.constraints:
        pf.constraints.append({"code": c.constraint_id, "currency": c.currency, "severity": c.severity, "blocks_new_investment": c.blocks_new_investment})
    if base is not None:
        from app.explain.next_action import next_action_kind

        pf.next_action = next_action_kind(result)
    return pf
