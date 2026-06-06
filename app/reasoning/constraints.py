from __future__ import annotations

from typing import Any, Literal


ConstraintSeverity = Literal["low", "medium", "high"]


def detect_constraints(profile: dict[str, Any], metrics: dict[str, Any]) -> list[dict[str, Any]]:
    constraints: list[dict[str, Any]] = []

    free_cf = float(metrics.get("free_cashflow") or 0.0)
    if free_cf < 0:
        constraints.append(
            {
                "constraint_id": "negative_cashflow",
                "severity": "high",
                "message": "Monthly expenses exceed monthly income.",
                "evidence": {"free_cashflow": free_cf},
            }
        )

    emergency = metrics.get("emergency_fund_months")
    if emergency is not None and float(emergency) < 3.0:
        constraints.append(
            {
                "constraint_id": "insufficient_emergency_fund",
                "severity": "high" if float(emergency) < 1.0 else "medium",
                "message": "Emergency fund coverage is below the recommended minimum.",
                "evidence": {"emergency_fund_months": float(emergency)},
            }
        )

    total_assets = float(metrics.get("total_assets") or 0.0)
    total_liabilities = float(metrics.get("total_liabilities") or 0.0)
    if total_liabilities > 0:
        ratio = total_liabilities / (total_assets if total_assets > 0 else 1.0)
        if total_assets <= 0 or ratio >= 0.6:
            constraints.append(
                {
                    "constraint_id": "high_debt_ratio",
                    "severity": "high" if total_assets <= 0 or ratio >= 1.0 else "medium",
                    "message": "Liabilities are high relative to assets.",
                    "evidence": {"debt_to_assets_ratio": ratio, "total_assets": total_assets, "total_liabilities": total_liabilities},
                }
            )

    debt_to_income = metrics.get("debt_to_income_ratio")
    if debt_to_income is not None and float(debt_to_income) >= 0.4:
        constraints.append(
            {
                "constraint_id": "high_debt_to_income_ratio",
                "severity": "medium" if float(debt_to_income) < 0.6 else "high",
                "message": "Total liabilities are high relative to income.",
                "evidence": {"debt_to_income_ratio": float(debt_to_income)},
            }
        )

    debt_service = metrics.get("debt_service_ratio")
    if debt_service is not None and float(debt_service) >= 0.2:
        constraints.append(
            {
                "constraint_id": "high_debt_service_ratio",
                "severity": "medium" if float(debt_service) < 0.35 else "high",
                "message": "Monthly debt service is high relative to income.",
                "evidence": {"debt_service_ratio": float(debt_service)},
            }
        )

    savings_rate = float(metrics.get("savings_rate") or 0.0)
    if 0 <= savings_rate < 0.1:
        constraints.append(
            {
                "constraint_id": "low_savings_rate",
                "severity": "low",
                "message": "The savings rate is low relative to income.",
                "evidence": {"savings_rate": savings_rate},
            }
        )

    high_apr_debt_count = int(metrics.get("high_apr_debt_count") or 0)
    if high_apr_debt_count > 0:
        constraints.append(
            {
                "constraint_id": "high_apr_debt_present",
                "severity": "medium",
                "message": "High-interest liabilities are present.",
                "evidence": {"high_apr_debt_count": high_apr_debt_count},
            }
        )

    return constraints

