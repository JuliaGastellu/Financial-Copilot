from __future__ import annotations

import math
from typing import Any


def estimate_available_capital(profile: dict[str, Any], metrics: dict[str, Any]) -> float:
    assets = profile.get("assets") or []
    liquid = 0.0
    for a in assets:
        if not isinstance(a, dict):
            continue
        if a.get("liquidity") not in ("high", "medium"):
            continue
        liquid += float(a.get("value") or 0.0)
    free_cf = float(metrics.get("free_cashflow") or 0.0)
    return max(0.0, liquid + max(0.0, free_cf))


def attach_goal_impacts(
    *,
    profile: dict[str, Any],
    metrics: dict[str, Any],
    recommendations: list[dict[str, Any]],
) -> None:
    goals = [g for g in (profile.get("goals") or []) if isinstance(g, dict)]
    free_cf = float(metrics.get("free_cashflow") or 0.0)
    base_monthly_allocation = max(0.0, free_cf * 0.5)

    for rec in recommendations:
        if not isinstance(rec, dict):
            continue
        impacted = _impacted_goals(goals, rec, base_monthly_allocation)
        rec["impacted_goals"] = impacted
        rec["projected_impact"] = _projected_impact_summary(impacted, base_monthly_allocation)


def attach_suggested_amounts(
    *,
    profile: dict[str, Any],
    metrics: dict[str, Any],
    recommendations: list[dict[str, Any]],
    available_capital: float,
) -> None:
    prefs = profile.get("preferences") or {}
    currency = str(prefs.get("currency") or "USD").upper()
    free_cf = float(metrics.get("free_cashflow") or 0.0)
    monthly_budget = max(0.0, free_cf * 0.5)
    for rec in recommendations:
        if not isinstance(rec, dict):
            continue
        if rec.get("opportunity") and isinstance(rec["opportunity"], dict):
            op = rec["opportunity"]
            min_cap = float(op.get("minimum_capital") or 0.0)
            suggested = min(available_capital, max(min_cap, available_capital * 0.1))
            rec["suggested_amount"] = round(max(0.0, suggested), 2)
            rec["suggested_currency"] = str(op.get("currency") or currency).upper()
            continue

        title = str(rec.get("title") or "").lower()
        if "allocate free cashflow" in title:
            rec["suggested_amount"] = round(monthly_budget, 2)
            rec["suggested_currency"] = currency
        elif "debt" in title or "debt payoff" in title:
            rec["suggested_amount"] = round(max(0.0, free_cf * 0.3), 2)
            rec["suggested_currency"] = currency


def _priority_weight(priority: str) -> float:
    return {"high": 1.0, "medium": 0.6, "low": 0.3}.get(priority, 0.6)


def _mid_expected_return(opportunity: dict[str, Any] | None) -> float | None:
    if not opportunity:
        return None
    rr = opportunity.get("expected_return_range")
    if not isinstance(rr, dict):
        return None
    try:
        return (float(rr.get("min_annual")) + float(rr.get("max_annual"))) / 2.0
    except Exception:
        return None


def _months_to_goal_simple(target_amount: float, monthly_allocation: float, current_amount: float = 0.0) -> int | None:
    remaining = max(0.0, target_amount - current_amount)
    if remaining <= 0:
        return 0
    if monthly_allocation <= 0:
        return None
    return int(math.ceil(remaining / monthly_allocation))


def _months_to_goal_with_return(target_amount: float, monthly_allocation: float, annual_return: float, current_amount: float = 0.0) -> int | None:
    remaining = max(0.0, target_amount - current_amount)
    if remaining <= 0:
        return 0
    if monthly_allocation <= 0:
        return None
    monthly_rate = (1.0 + annual_return) ** (1.0 / 12.0) - 1.0
    if monthly_rate <= 0:
        return _months_to_goal_simple(target_amount, monthly_allocation, current_amount)
    balance = current_amount
    for m in range(1, 721):
        balance = balance * (1.0 + monthly_rate) + monthly_allocation
        if balance >= target_amount:
            return m
    return None


def _impacted_goals(goals: list[dict[str, Any]], rec: dict[str, Any], base_monthly_allocation: float) -> list[dict[str, Any]]:
    impacted: list[dict[str, Any]] = []
    opportunity = rec.get("opportunity") if isinstance(rec.get("opportunity"), dict) else None
    annual_return = _mid_expected_return(opportunity)
    risk_level = None
    if opportunity:
        risk_level = opportunity.get("risk_level")
    allocation = base_monthly_allocation
    if opportunity is not None:
        allocation = max(0.0, base_monthly_allocation * 0.5)

    for g in goals:
        name = str(g.get("name") or "").strip()
        if not name:
            continue
        priority = str(g.get("priority") or "medium")
        target_amount = float(g.get("target_amount") or 0.0)
        current_amount = float(g.get("current_amount") or 0.0)
        horizon_months = g.get("horizon_months")
        horizon_months = int(horizon_months) if isinstance(horizon_months, int) and horizon_months > 0 else None

        baseline = _months_to_goal_simple(target_amount, allocation, current_amount)
        improved = baseline
        if annual_return is not None:
            improved = _months_to_goal_with_return(target_amount, allocation, annual_return, current_amount)

        time_delta = None
        if baseline is not None and improved is not None:
            time_delta = int(improved - baseline)

        probability = 0.55 + 0.15 * (allocation > 0)
        if risk_level == "low":
            probability += 0.1
        elif risk_level == "high":
            probability -= 0.1
        if horizon_months is not None and improved is not None:
            probability += 0.1 if improved <= horizon_months else -0.1
        if current_amount >= target_amount:
            probability = 1.0
        probability = min(1.0, max(0.0, probability))

        impacted.append(
            {
                "goal_name": name,
                "priority": priority,
                "horizon_months": horizon_months,
                "capital_allocation_effect": {
                    "estimated_monthly_allocation": allocation,
                    "assumed_annual_return_mid": annual_return,
                },
                "time_to_goal_change": time_delta,
                "probability_of_success": probability,
                "confidence": min(1.0, 0.55 + 0.4 * _priority_weight(priority)),
            }
        )

    impacted.sort(key=lambda x: _priority_weight(str(x.get("priority"))), reverse=True)
    return impacted[:3]


def _projected_impact_summary(impacted_goals: list[dict[str, Any]], base_monthly_allocation: float) -> dict[str, Any]:
    if not impacted_goals:
        return {
            "time_delta": None,
            "confidence": 0.4,
            "explanation": "No explicit goals were provided in the profile. Impact estimates are unavailable.",
        }
    deltas = [g.get("time_to_goal_change") for g in impacted_goals if isinstance(g.get("time_to_goal_change"), int)]
    confidence = float(sum(float(g.get("confidence") or 0.0) for g in impacted_goals) / max(1, len(impacted_goals)))
    if not deltas:
        return {
            "time_delta": None,
            "confidence": min(1.0, max(0.0, confidence)),
            "explanation": "Insufficient free cashflow or missing goal parameters prevent estimating time-to-goal changes.",
        }
    avg_delta = int(round(sum(deltas) / len(deltas)))
    return {
        "time_delta": avg_delta,
        "confidence": min(1.0, max(0.0, confidence)),
        "explanation": f"Estimated impact assumes an average monthly allocation of {base_monthly_allocation:.0f} from free cashflow.",
    }
