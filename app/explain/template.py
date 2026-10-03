"""Explicación determinística de respaldo, construida solo con los hechos del plan.

La uso cuando el proveedor está deshabilitado, falla, excede límites o contradice el plan.
Produce la misma estructura que la salida del proveedor y pasa la misma validación.
"""
from __future__ import annotations

from decimal import Decimal

from app.explain.facts import PRIORITY_ES, PlanFacts
from app.explain.validation import ExplanationOutput, ExplanationPoint

STATUS_ES = {
    "achieved": "ya está cumplida",
    "funded_now": "queda cubierta con tu saldo actual",
    "on_track": "va en camino",
    "underfunded": "no llega con el aporte disponible",
    "overdue": "tiene la fecha vencida",
    "no_deadline": "no tiene fecha",
}

CONSTRAINT_ES = {
    "negative_cashflow": "Tus salidas superan tus ingresos, así que no se reparte dinero en esa moneda.",
    "zero_income": "No hay ingresos registrados, así que no hay aportes mensuales.",
    "commitments_exceed_liquid_balance": "Tus compromisos superan tu saldo disponible.",
    "insufficient_emergency_fund": "La reserva de emergencia está incompleta y se completa antes que las metas.",
    "high_apr_debt_present": "Hay deuda con tasa alta, que se paga después de la reserva y antes que las metas.",
    "high_debt_service_ratio": "Los pagos de deuda ocupan una parte alta del ingreso.",
    "high_debt_to_assets_ratio": "La deuda es alta frente a los activos.",
    "low_savings_rate": "El margen de ahorro es bajo.",
    "goal_shortfall": "Algunas metas no llegan con este reparto.",
    "goal_currency_without_income": "Hay metas en una moneda sin ingresos en esa moneda.",
}


def money(amount: Decimal, currency: str) -> str:
    quantized = amount.quantize(Decimal("0.01"))
    sign = "-" if quantized < 0 else ""
    whole, cents = f"{abs(quantized):.2f}".split(".")
    groups = []
    while whole:
        groups.insert(0, whole[-3:])
        whole = whole[:-3]
    return f"{sign}{currency} {'.'.join(groups)},{cents}"


def _fact(pf: PlanFacts, kind: str, currency: str | None = None, goal: str | None = None) -> str:
    for f in pf.facts.values():
        if f.kind == kind and (currency is None or f.currency == currency) and (goal is None or f.goal == goal):
            return f.id
    raise KeyError(kind)


def build_template(pf: PlanFacts) -> ExplanationOutput:
    c = pf.base_currency
    surplus_id = _fact(pf, "monthly_surplus", c)
    surplus = pf.facts[surplus_id].amount or Decimal(0)
    reserve_id = _fact(pf, "reserve_contribution", c)
    debt_id = _fact(pf, "high_apr_debt_payment", c)
    goals_id = _fact(pf, "goal_contributions", c)
    unassigned_id = _fact(pf, "unassigned_monthly", c)
    F = pf.facts

    if surplus < 0:
        summary = ExplanationPoint(
            text=f"Este mes tus salidas superan tus ingresos en {money(-surplus, c)}, así que el plan no reparte dinero.",
            facts=[surplus_id],
        )
    else:
        summary = ExplanationPoint(
            text=f"Este mes tenés {money(surplus, c)} para repartir según el plan.",
            facts=[surplus_id],
        )
    points = [
        ExplanationPoint(
            text=(
                f"El reparto va primero a la reserva ({money(F[reserve_id].amount or Decimal(0), c)}), "
                f"después a la deuda con tasa alta ({money(F[debt_id].amount or Decimal(0), c)}) "
                f"y luego a las metas ({money(F[goals_id].amount or Decimal(0), c)})."
            ),
            facts=[reserve_id, debt_id, goals_id],
        )
    ]
    if (F[unassigned_id].amount or Decimal(0)) > 0:
        points.append(
            ExplanationPoint(text=f"Quedan {money(F[unassigned_id].amount or Decimal(0), c)} sin asignar.", facts=[unassigned_id])
        )
    for g in pf.goals[:3]:
        monthly = F[g["monthly_fact"]]
        text = f"{g['label']}, de prioridad {PRIORITY_ES[g['priority']]}, {STATUS_ES[g['status']]}: recibe {money(monthly.amount or Decimal(0), monthly.currency or c)} por mes."
        facts = [g["monthly_fact"]]
        if "shortfall_fact" in g:
            shortfall = F[g["shortfall_fact"]]
            text = text[:-1] + f" y le faltan {money(shortfall.amount or Decimal(0), shortfall.currency or c)} por mes."
            facts.append(g["shortfall_fact"])
        points.append(ExplanationPoint(text=text, facts=facts))
    blocking = [x for x in pf.constraints if x["code"] in CONSTRAINT_ES]
    if blocking and len(points) < 6:
        reserve_target = _fact(pf, "reserve_target", c)
        points.append(
            ExplanationPoint(
                text=" ".join(dict.fromkeys(CONSTRAINT_ES[x["code"]] for x in blocking))[:400],
                facts=[reserve_target],
            )
        )
    return ExplanationOutput(summary=summary, points=points[:6])


def render(output: ExplanationOutput, pf: PlanFacts) -> ExplanationOutput:
    """Restituyo los nombres reales de las metas en el servidor, después de validar."""
    def swap(text: str) -> str:
        for label in sorted(pf.labels, key=len, reverse=True):
            text = text.replace(label, f"«{pf.labels[label]}»")
        return text

    return ExplanationOutput(
        summary=ExplanationPoint(text=swap(output.summary.text)[:400], facts=output.summary.facts),
        points=[ExplanationPoint(text=swap(p.text)[:400], facts=p.facts) for p in output.points],
    )
