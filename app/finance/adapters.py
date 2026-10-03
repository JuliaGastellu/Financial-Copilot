"""Traduzco perfiles guardados (actuales o anteriores) al modelo de dominio.

Registro como supuesto o dato faltante cada valor que no viene declarado, en lugar
de completarlo en silencio.
"""
from __future__ import annotations

from datetime import date
from typing import Any

from app.finance.model import Balance, Commitment, Debt, FinancialSnapshot, Goal, MonthlyCashflow
from app.finance.money import Money, normalize_currency, to_decimal

DEFAULT_CURRENCY = "USD"


def _currency_or(value: Any, fallback: str) -> str:
    return normalize_currency(value) if value else fallback


def _money(value: Any, currency: str, rounded: list[str], label: str) -> Money:
    raw = Money(to_decimal(value if value is not None else 0), currency)
    result = raw.round()
    if result.amount != raw.amount:
        rounded.append(label)
    return result


def _parse_date(value: Any) -> date | None:
    if value is None or value == "":
        return None
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value))


def resolve_base_currency(profile: dict[str, Any]) -> tuple[str, list[str]]:
    prefs = profile.get("preferences") or {}
    if profile.get("currency"):
        return normalize_currency(profile["currency"]), []
    if isinstance(prefs, dict) and prefs.get("currency"):
        return normalize_currency(prefs["currency"]), []
    return DEFAULT_CURRENCY, [f"base_currency_defaulted_to_{DEFAULT_CURRENCY}"]


def snapshot_from_profile(profile: dict[str, Any], as_of: date) -> FinancialSnapshot:
    base, assumptions = resolve_base_currency(profile)
    missing: list[str] = []
    rounded: list[str] = []

    cashflow = profile.get("cashflow") or {}
    cf_currency = _currency_or(cashflow.get("currency"), base)
    included = cashflow.get("minimum_payments_included_in_expenses")
    cashflows = [
        MonthlyCashflow(
            income=_money(cashflow.get("monthly_income"), cf_currency, rounded, "monthly_income"),
            expenses=_money(cashflow.get("monthly_expenses"), cf_currency, rounded, "monthly_expenses"),
            minimum_payments_included=included,
        )
    ]
    for i, extra in enumerate(profile.get("additional_cashflows") or []):
        if not isinstance(extra, dict):
            continue
        currency = normalize_currency(extra.get("currency"))
        cashflows.append(
            MonthlyCashflow(
                income=_money(extra.get("monthly_income"), currency, rounded, f"additional_cashflows[{i}].monthly_income"),
                expenses=_money(extra.get("monthly_expenses"), currency, rounded, f"additional_cashflows[{i}].monthly_expenses"),
                minimum_payments_included=extra.get("minimum_payments_included_in_expenses"),
            )
        )

    balances = []
    for a in profile.get("assets") or []:
        if not isinstance(a, dict):
            continue
        currency = _currency_or(a.get("currency"), base)
        balances.append(
            Balance(
                name=str(a.get("name") or "asset"),
                amount=_money(a.get("value"), currency, rounded, f"asset:{a.get('name')}"),
                liquidity=a.get("liquidity") or "medium",
                category=str(a.get("category") or "other"),
            )
        )

    debts = []
    for item in profile.get("liabilities") or []:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "debt")
        currency = _currency_or(item.get("currency"), base)
        balance = _money(item.get("balance"), currency, rounded, f"debt:{name}")
        minimum = item.get("minimum_payment")
        if minimum is None and balance.is_positive():
            missing.append(f"minimum_payment_unknown:{name}")
        apr = item.get("apr")
        if apr is None and balance.is_positive():
            missing.append(f"apr_unknown:{name}")
        debts.append(
            Debt(
                name=name,
                balance=balance,
                apr_percent=to_decimal(apr) if apr is not None else None,
                minimum_payment=_money(minimum, currency, rounded, f"debt_minimum:{name}") if minimum is not None else None,
            )
        )

    if debts and any(c.minimum_payments_included is None for c in cashflows):
        assumptions.append("minimum_payments_assumed_not_included_in_expenses")

    goals = []
    for g in profile.get("goals") or []:
        if not isinstance(g, dict):
            continue
        name = str(g.get("name") or "goal")
        currency = _currency_or(g.get("currency"), base)
        target_date = _parse_date(g.get("target_date"))
        horizon = g.get("horizon_months")
        if target_date is not None and horizon is not None:
            assumptions.append(f"target_date_used_over_horizon:{name}")
        if target_date is None and horizon is None:
            missing.append(f"goal_deadline_unknown:{name}")
        goals.append(
            Goal(
                name=name,
                target=_money(g.get("target_amount"), currency, rounded, f"goal_target:{name}"),
                saved=_money(g.get("current_amount"), currency, rounded, f"goal_saved:{name}"),
                priority=g.get("priority") or "medium",
                target_date=target_date,
                horizon_months=int(horizon) if horizon is not None else None,
                goal_id=str(g["goal_id"]) if g.get("goal_id") else None,
            )
        )

    commitments = []
    for c in profile.get("commitments") or []:
        if not isinstance(c, dict):
            continue
        name = str(c.get("name") or "commitment")
        currency = _currency_or(c.get("currency"), base)
        commitments.append(
            Commitment(name=name, amount=_money(c.get("amount"), currency, rounded, f"commitment:{name}"), kind=c.get("kind") or "monthly")
        )

    reserve = profile.get("emergency_reserve_months")
    provenance = profile.get("provenance") or {}
    for field in ("monthly_income", "monthly_expenses", "balances", "reserve_months"):
        status = provenance.get(field, "reported")
        if status == "estimated":
            assumptions.append(f"{field}_estimated")
        elif status == "unknown":
            missing.append(f"{field}_unknown")
    if rounded:
        assumptions.append("amounts_rounded_to_currency_minor_unit:" + ",".join(rounded))

    return FinancialSnapshot(
        as_of=as_of,
        base_currency=base,
        cashflows=tuple(cashflows),
        balances=tuple(balances),
        debts=tuple(debts),
        goals=tuple(goals),
        commitments=tuple(commitments),
        reserve_months=to_decimal(reserve) if reserve is not None else None,
        assumptions=tuple(assumptions),
        missing_data=tuple(missing),
    )


def planning_profile_from_v1(profile: dict[str, Any], goals: list[dict[str, Any]]) -> dict[str, Any]:
    """Traduzco el contrato v1 (importes con moneda) al formato que consume `snapshot_from_profile`."""
    base = normalize_currency(profile["currency"])
    cashflows = list(profile.get("cashflows") or [])
    main = next((c for c in cashflows if normalize_currency(c["currency"]) == base), cashflows[0] if cashflows else None)

    def flow(c: dict[str, Any]) -> dict[str, Any]:
        return {
            "currency": c["currency"],
            "monthly_income": str(c["monthly_income"]),
            "monthly_expenses": str(c["monthly_expenses"]),
            "minimum_payments_included_in_expenses": c.get("minimum_payments_included_in_expenses"),
        }

    return {
        "currency": base,
        "country": profile.get("country"),
        "risk_tolerance": profile.get("risk_tolerance") or "medium",
        "cashflow": flow(main) if main else {"monthly_income": "0", "monthly_expenses": "0", "currency": base},
        "additional_cashflows": [flow(c) for c in cashflows if c is not main],
        "assets": [
            {
                "name": a["name"],
                "category": a.get("category") or "other",
                "liquidity": a["liquidity"],
                "value": str(a["value"]["amount"]),
                "currency": a["value"]["currency"],
            }
            for a in profile.get("assets") or []
        ],
        "liabilities": [
            {
                "name": item["name"],
                "balance": str(item["balance"]["amount"]),
                "currency": item["balance"]["currency"],
                "apr": str(item["apr_percent"]) if item.get("apr_percent") is not None else None,
                "minimum_payment": str(item["minimum_payment"]["amount"]) if item.get("minimum_payment") else None,
            }
            for item in profile.get("liabilities") or []
        ],
        "commitments": [
            {"name": c["name"], "kind": c["kind"], "amount": str(c["amount"]["amount"]), "currency": c["amount"]["currency"]}
            for c in profile.get("commitments") or []
        ],
        "emergency_reserve_months": str(profile["emergency_reserve_months"]) if profile.get("emergency_reserve_months") is not None else None,
        "provenance": profile.get("provenance") or {},
        "goals": [
            {
                "name": g["name"],
                "currency": g["currency"],
                "target_amount": str(g["target_amount"]),
                "current_amount": str(g["saved_amount"]),
                "priority": g["priority"],
                "target_date": g["target_date"].isoformat() if hasattr(g.get("target_date"), "isoformat") else g.get("target_date"),
                "horizon_months": g.get("horizon_months"),
            }
            for g in goals
        ],
    }
