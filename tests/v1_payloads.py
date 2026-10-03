"""Datos ficticios para pruebas v1."""
from __future__ import annotations

import uuid
from typing import Any


def money(amount: str | int, currency: str = "USD") -> dict[str, str]:
    return {"amount": str(amount), "currency": currency}


def profile_v1(**overrides: Any) -> dict[str, Any]:
    profile: dict[str, Any] = {
        "currency": "USD",
        "country": "US",
        "risk_tolerance": "medium",
        "cashflows": [{"currency": "USD", "monthly_income": "7000", "monthly_expenses": "4500"}],
        "assets": [{"name": "Cash", "category": "cash", "liquidity": "high", "value": money(8000)}],
        "liabilities": [],
        "commitments": [],
    }
    profile.update(overrides)
    return profile


def goal_v1(name: str = "Down payment", amount: str | int = 20000, **overrides: Any) -> dict[str, Any]:
    goal: dict[str, Any] = {"name": name, "target": money(amount), "priority": "high", "horizon_months": 18}
    goal.update(overrides)
    return goal


def idem(headers: dict[str, str]) -> dict[str, str]:
    """Agrego una clave de idempotencia nueva a los encabezados de una creación."""
    return {**headers, "Idempotency-Key": f"test-{uuid.uuid4()}"}


def provenance(source: str = "https://example.invalid/corpus", valid_until: str = "2099-01-01"):
    """Procedencia ficticia para documentos de prueba del corpus público."""
    from datetime import date

    from app.data.documents import Provenance

    return Provenance(
        publisher="Material ficticio para pruebas",
        source=source,
        published_on=date(2026, 1, 1),
        reviewed_on=date(2026, 9, 1),
        valid_until=date.fromisoformat(valid_until),
    )
