"""Compatibilidad de lectura para decisiones guardadas con contratos anteriores.

Las decisiones anteriores pueden incluir `probability_of_success` y `confidence`,
calculados con constantes sin calibrar. No los reescribo en la base: los quito al
leerlos y marco el registro para que se note que el contenido cambió.
"""
from __future__ import annotations

from typing import Any

UNCALIBRATED_KEYS = frozenset({"probability_of_success", "confidence"})


def _strip(value: Any) -> tuple[Any, bool]:
    if isinstance(value, dict):
        removed = False
        out: dict[str, Any] = {}
        for k, v in value.items():
            if k in UNCALIBRATED_KEYS:
                removed = True
                continue
            cleaned, child_removed = _strip(v)
            removed = removed or child_removed
            out[k] = cleaned
        return out, removed
    if isinstance(value, list):
        removed = False
        items = []
        for item in value:
            cleaned, child_removed = _strip(item)
            removed = removed or child_removed
            items.append(cleaned)
        return items, removed
    return value, False


def strip_uncalibrated_indicators(decision: dict[str, Any]) -> dict[str, Any]:
    cleaned, removed = _strip(decision)
    if removed:
        context = cleaned.setdefault("decision_context", {})
        if isinstance(context, dict):
            context["legacy_indicators_removed"] = sorted(UNCALIBRATED_KEYS)
    return cleaned
