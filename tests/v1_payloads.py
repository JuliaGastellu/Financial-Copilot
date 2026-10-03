"""Datos ficticios para pruebas v1."""
from __future__ import annotations

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
