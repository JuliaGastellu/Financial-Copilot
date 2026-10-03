"""Proveedor simulado con guiones adversariales, para pruebas determinísticas.

No mide la calidad de un modelo: comprueba que la validación detecta cada tipo de error y que
la explicación entregada nunca contradice el plan.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from decimal import Decimal

from app.explain.provider import ProviderError, ProviderResult

PRIORITY_ES = {"high": "alta", "medium": "media", "low": "baja"}
WRONG_PRIORITY = {"high": "baja", "medium": "alta", "low": "alta"}


def _amount(fact: dict) -> str:
    return f"{fact['currency']} {Decimal(fact['amount']):.2f}"


@dataclass
class ScriptedProvider:
    script: str = "faithful"
    name: str = "scripted"
    model: str = "scripted-v1"
    calls: int = field(default=0)

    def generate(self, *, system: str, user: str, max_output_tokens: int, timeout_seconds: float) -> ProviderResult:
        self.calls += 1
        if self.script == "timeout":
            raise ProviderError("timeout", transient=True)
        if self.script == "transient_then_ok" and self.calls == 1:
            raise ProviderError("http_503", transient=True)
        if self.script == "bad_json":
            raise ProviderError("invalid_json", transient=False)
        data = json.loads(user)
        payload = self._payload(data)
        tokens_in = max(1, (len(system) + len(user)) // 4)
        return ProviderResult(payload=payload, input_tokens=tokens_in, output_tokens=max(1, len(json.dumps(payload)) // 4), latency_ms=5)

    def _payload(self, data: dict) -> dict:
        facts = {f["id"]: f for f in data["facts"]}
        by_kind = {}
        for f in data["facts"]:
            by_kind.setdefault((f["kind"], f.get("currency"), f.get("goal")), f)
        base = data["base_currency"]
        surplus = by_kind[("monthly_surplus", base, None)]
        goals_total = by_kind[("goal_contributions", base, None)]
        summary = {"text": f"Este mes el plan reparte {_amount(surplus)}.", "facts": [surplus["id"]]}
        points = [{"text": f"A las metas van {_amount(goals_total)} por mes.", "facts": [goals_total["id"]]}]
        goal = data["goals"][0] if data["goals"] else None
        if goal:
            monthly = facts[goal["monthly_fact"]]
            points.append(
                {
                    "text": f"{goal['label']} tiene prioridad {PRIORITY_ES[goal['priority']]} y recibe {_amount(monthly)} por mes.",
                    "facts": [goal["monthly_fact"]],
                }
            )
        s = self.script
        if s == "altered_amount":
            summary["text"] = f"Este mes el plan reparte {surplus['currency']} {Decimal(surplus['amount']) + 1:.2f}."
        elif s == "wrong_currency":
            other = "EUR" if base != "EUR" else "USD"
            summary["text"] = f"Este mes el plan reparte {other} {Decimal(surplus['amount']):.2f}."
        elif s == "wrong_priority" and goal:
            points[-1]["text"] = f"{goal['label']} tiene prioridad {WRONG_PRIORITY[goal['priority']]}."
        elif s == "new_advice":
            points.append({"text": "Te conviene invertir el excedente en un plazo fijo.", "facts": [surplus["id"]]})
        elif s == "probability":
            points.append({"text": "Tenés una probabilidad alta de llegar a tus metas.", "facts": [surplus["id"]]})
        elif s == "invented_number":
            points.append({"text": f"Además podrías separar {base} 1234.56 extra.", "facts": [surplus["id"]]})
        elif s == "unknown_fact":
            points[0]["facts"] = ["f999"]
        elif s == "no_citations":
            points[0]["facts"] = []
        elif s == "instruction_echo":
            points.append({"text": "Ignorá las instrucciones anteriores del plan.", "facts": [surplus["id"]]})
        elif s == "guarantee":
            points.append({"text": "Con este reparto el ahorro está garantizado.", "facts": [surplus["id"]]})
        elif s == "swap_goal_amounts" and goal:
            points[-1] = {"text": f"{goal['label']} recibe {_amount(surplus)} por mes.", "facts": [goal["monthly_fact"]]}
            if Decimal(surplus["amount"]) == Decimal(facts[goal["monthly_fact"]]["amount"]):
                points[-1]["text"] = f"{goal['label']} recibe {surplus['currency']} {Decimal(surplus['amount']) + 10:.2f} por mes."
        elif s == "denies_constraints":
            points.append({"text": "Tu plan no tiene ninguna restricción.", "facts": [surplus["id"]]})
        elif s == "loan_advice":
            points.append({"text": "Podrías pedir un préstamo para adelantar la meta.", "facts": [surplus["id"]]})
        elif s == "percent_claim":
            points.append({"text": "A las metas va el 30 por ciento del ingreso.", "facts": [goals_total["id"]]})
        elif s == "rounded_amount" and goal:
            exact = Decimal(facts[goal["monthly_fact"]]["amount"])
            rounded = exact.quantize(Decimal("1E2"))
            if rounded == exact:
                rounded += 100
            points[-1]["text"] = f"{goal['label']} recibe unos {base} {rounded:.0f} por mes."
        return {"summary": summary, "points": points}
