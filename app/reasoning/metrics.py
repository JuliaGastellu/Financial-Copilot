from __future__ import annotations

from typing import Any


def compute_profile_metrics(profile: dict[str, Any]) -> dict[str, Any]:
    cashflow = profile.get("cashflow") or {}
    income = float(cashflow.get("monthly_income") or 0.0)
    expenses = float(cashflow.get("monthly_expenses") or 0.0)
    free_cashflow = income - expenses
    savings_rate = (free_cashflow / income) if income > 0 else 0.0

    assets = profile.get("assets") or []
    liabilities = profile.get("liabilities") or []
    total_assets = sum(float(a.get("value") or 0.0) for a in assets if isinstance(a, dict))
    total_liabilities = sum(float(l.get("balance") or 0.0) for l in liabilities if isinstance(l, dict))
    total_minimum_payments = sum(float(l.get("minimum_payment") or 0.0) for l in liabilities if isinstance(l, dict))

    liquid_assets = sum(
        float(a.get("value") or 0.0)
        for a in assets
        if isinstance(a, dict) and a.get("liquidity") in ("high", "medium")
    )
    emergency_fund_months = (liquid_assets / expenses) if expenses > 0 else None

    debt_service_ratio = (total_minimum_payments / income) if income > 0 else None
    debt_to_income_ratio = (total_liabilities / income) if income > 0 else None

    high_apr_debt = [
        l
        for l in liabilities
        if isinstance(l, dict) and (l.get("apr") is not None) and float(l.get("apr")) >= 12.0
    ]

    return {
        "monthly_income": income,
        "monthly_expenses": expenses,
        "free_cashflow": free_cashflow,
        "savings_rate": round(savings_rate, 4),
        "total_assets": total_assets,
        "total_liabilities": total_liabilities,
        "net_worth": total_assets - total_liabilities,
        "liquid_assets": liquid_assets,
        "emergency_fund_months": emergency_fund_months,
        "debt_service_ratio": round(debt_service_ratio, 4) if debt_service_ratio is not None else None,
        "debt_to_income_ratio": round(debt_to_income_ratio, 4) if debt_to_income_ratio is not None else None,
        "high_apr_debt_count": len(high_apr_debt),
    }

