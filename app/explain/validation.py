"""Contrato de salida de la explicación y validación contra los hechos del plan.

La explicación solo puede describir el plan. Rechazo cualquier salida que:
- no respete el esquema JSON o los límites de longitud;
- cite hechos inexistentes o deje un punto sin citas;
- mencione un número que no coincida con un hecho citado en ese mismo punto;
- mencione una moneda ajena a los hechos citados;
- atribuya a una meta una prioridad distinta de la del plan;
- niegue restricciones que el plan tiene;
- agregue probabilidades, garantías, recomendaciones de instrumentos o decisiones nuevas.
"""
from __future__ import annotations

import re
import unicodedata
from decimal import Decimal, InvalidOperation
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, ValidationError

from app.explain.facts import PRIORITY_ES, PlanFacts

Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=400)]


class ExplanationPoint(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: Text
    facts: list[Annotated[str, StringConstraints(pattern=r"^f\d{1,4}$")]] = Field(min_length=1, max_length=8)


class ExplanationOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    summary: ExplanationPoint
    points: list[ExplanationPoint] = Field(min_length=1, max_length=6)


class ExplanationRejected(Exception):
    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail


def _fold(text: str) -> str:
    folded = unicodedata.normalize("NFKD", text.lower())
    return "".join(c for c in folded if not unicodedata.combining(c))


_FORBIDDEN = [
    (re.compile(p), code)
    for p, code in (
        (r"probabilidad|probable|chance|posibilidad(es)? de (exito|lograr)|\d+\s*%|por ciento", "probability_claim"),
        (r"garantiz|asegurad|sin riesgo|seguro que", "guarantee_claim"),
        (r"\binvert\w*|\binversion\w*|acciones\b|\bbonos?\b|cripto|bitcoin|cedear|plazo fijo|fondo comun", "investment_advice"),
        (r"\bcompr(a|as|e|en|ar|alo|ala)\b|\bvend(e|es|en|er|elo|ela)\b", "investment_advice"),
        (r"prestamo|endeud|refinanci|tarjeta de credito|pedi (un|plata)", "new_decision"),
        (r"(cambia|modifica|subi|baja)\w*\s+(tu|el)\s+(plan|presupuesto|reparto)|en lugar de lo que (dice|indica) el plan", "new_decision"),
        (r"ignor\w*\s+(las\s+)?(instrucciones|reglas)|system prompt", "instruction_echo"),
    )
]
_NO_CONSTRAINTS = re.compile(r"(no hay|sin|ninguna)\s+restriccion")
# Números con separadores de miles o decimales en formato local o con punto decimal.
_NUMBER = re.compile(r"(?<![\w.,])-?\d{1,3}(?:[.\s]\d{3})+(?:,\d{1,2})?(?![\d])|(?<![\w.,])-?\d+(?:[.,]\d{1,2})?(?![\d])")
_CURRENCY = re.compile(r"\b[A-Z]{3}\b")
_LABEL = re.compile(r"meta-\d{1,3}")
_PRIORITY_WORD = re.compile(r"prioridad\s+(alta|media|baja)")


def _parse_number(token: str) -> Decimal | None:
    t = token.replace(" ", "")
    sign = -1 if t.startswith("-") else 1
    t = t.lstrip("-")
    if re.fullmatch(r"\d{1,3}(\.\d{3})+(,\d{1,2})?", t):
        t = t.replace(".", "").replace(",", ".")
    elif "," in t:
        t = t.replace(",", ".")
    try:
        return Decimal(t) * sign
    except InvalidOperation:
        return None


def _allowed_numbers(pf: PlanFacts, fact_ids: list[str]) -> set[Decimal]:
    allowed: set[Decimal] = set()
    for fid in fact_ids:
        f = pf.facts[fid]
        if f.amount is not None:
            allowed.add(f.amount.quantize(Decimal("0.01")))
            # Un déficit puede expresarse como monto positivo; un monto positivo nunca como negativo.
            if f.amount < 0:
                allowed.add((-f.amount).quantize(Decimal("0.01")))
        if f.value is not None:
            try:
                allowed.add(Decimal(str(f.value)).quantize(Decimal("0.01")))
            except InvalidOperation:
                pass
    return allowed


def _check_point(pf: PlanFacts, point: ExplanationPoint) -> None:
    for fid in point.facts:
        if fid not in pf.facts:
            raise ExplanationRejected("unknown_fact", fid)
    text = point.text
    folded = _fold(text)
    for pattern, code in _FORBIDDEN:
        if pattern.search(folded):
            raise ExplanationRejected(code, text[:80])
    if pf.constraints and _NO_CONSTRAINTS.search(folded):
        raise ExplanationRejected("constraint_denied", text[:80])
    # Etiquetas de metas: deben existir; los números de la etiqueta no son cifras.
    labels = _LABEL.findall(folded)
    for label in labels:
        if label not in pf.labels:
            raise ExplanationRejected("unknown_goal", label)
    without_labels = _LABEL.sub(" ", text)
    allowed = _allowed_numbers(pf, point.facts)
    for token in _NUMBER.findall(without_labels):
        value = _parse_number(token)
        if value is None or value.quantize(Decimal("0.01")) not in allowed:
            raise ExplanationRejected("number_mismatch", token)
    cited_currencies = {pf.facts[f].currency for f in point.facts if pf.facts[f].currency}
    for code in _CURRENCY.findall(without_labels):
        if code not in cited_currencies:
            raise ExplanationRejected("currency_mismatch", code)
    goal_priority = {g["label"]: PRIORITY_ES[g["priority"]] for g in pf.goals}
    for sentence in re.split(r"(?<=[.;!?])\s+", folded):
        priorities = _PRIORITY_WORD.findall(sentence)
        sentence_labels = _LABEL.findall(sentence)
        if priorities and sentence_labels:
            expected = {goal_priority[label] for label in sentence_labels if label in goal_priority}
            if any(p not in expected for p in priorities):
                raise ExplanationRejected("priority_mismatch", sentence[:80])


def validate_output(pf: PlanFacts, raw: object) -> ExplanationOutput:
    try:
        output = ExplanationOutput.model_validate(raw)
    except ValidationError as exc:
        raise ExplanationRejected("schema_invalid", str(exc.errors()[0]["type"])) from exc
    for point in [output.summary, *output.points]:
        _check_point(pf, point)
    return output
