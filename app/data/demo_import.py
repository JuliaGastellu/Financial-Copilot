"""Importación controlada de perfiles de demostración del SQLite local anterior.

Solo importo perfiles que se nombran de forma explícita y que la persona operadora declara
ficticios. No importo historial de decisiones ni documentos.
"""
from __future__ import annotations

import json
import sqlite3
from decimal import Decimal
from pathlib import Path
from typing import Any

from app.finance.adapters import resolve_base_currency
from app.schemas.v1 import GoalInputV1, ProfileV1


def _money(value: Any, currency: str) -> dict[str, str]:
    return {"amount": format(Decimal(str(value or 0)).quantize(Decimal("0.01")), "f"), "currency": currency}


def legacy_profile_to_v1(profile: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    base, _ = resolve_base_currency(profile)
    cashflow = profile.get("cashflow") or {}
    v1 = {
        "currency": base,
        "country": (profile.get("country") or None),
        "risk_tolerance": profile.get("risk_tolerance") or "medium",
        "cashflows": [
            {
                "currency": base,
                "monthly_income": _money(cashflow.get("monthly_income"), base)["amount"],
                "monthly_expenses": _money(cashflow.get("monthly_expenses"), base)["amount"],
                "minimum_payments_included_in_expenses": cashflow.get("minimum_payments_included_in_expenses"),
            }
        ],
        "assets": [
            {
                "name": a.get("name") or "asset",
                "category": a.get("category") or "other",
                "liquidity": a.get("liquidity") or "medium",
                "value": _money(a.get("value"), a.get("currency") or base),
            }
            for a in profile.get("assets") or []
        ],
        "liabilities": [
            {
                "name": item.get("name") or "debt",
                "balance": _money(item.get("balance"), item.get("currency") or base),
                "apr_percent": str(item["apr"]) if item.get("apr") is not None else None,
                "minimum_payment": _money(item["minimum_payment"], item.get("currency") or base) if item.get("minimum_payment") is not None else None,
            }
            for item in profile.get("liabilities") or []
        ],
    }
    validated = ProfileV1.model_validate(v1).model_dump(mode="json")
    goals = [
        GoalInputV1.model_validate(
            {
                "name": g.get("name") or "goal",
                "target": _money(g.get("target_amount"), g.get("currency") or base),
                "saved": _money(g.get("current_amount"), g.get("currency") or base),
                "priority": g.get("priority") or "medium",
                "target_date": g.get("target_date"),
                "horizon_months": g.get("horizon_months"),
            }
        ).model_dump()
        for g in profile.get("goals") or []
    ]
    return validated, goals


def read_legacy_profiles(sqlite_path: Path, user_ids: list[str]) -> dict[str, dict[str, Any]]:
    conn = sqlite3.connect(f"file:{sqlite_path.as_posix()}?mode=ro", uri=True)
    try:
        found: dict[str, dict[str, Any]] = {}
        for user_id in user_ids:
            row = conn.execute("SELECT profile_json FROM profiles WHERE user_id = ?", (user_id,)).fetchone()
            if row is not None:
                found[user_id] = json.loads(row[0])
        return found
    finally:
        conn.close()
