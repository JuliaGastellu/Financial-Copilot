from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from app.opportunity_engine.decision_trace import DecisionTrace, OpportunityRejection, OpportunitySummary, ScoringBreakdown
from app.opportunity_engine.models import InvestmentOpportunity
from app.reasoning.metrics import compute_profile_metrics
from app.reasoning.constraints import detect_constraints


RiskLevel = Literal["low", "medium", "high"]
LiquidityLevel = Literal["high", "medium", "low"]


def _risk_allows(user: RiskLevel, instrument: RiskLevel) -> bool:
    order: dict[RiskLevel, int] = {"low": 0, "medium": 1, "high": 2}
    return order[instrument] <= order[user]


def _liquidity_order(level: LiquidityLevel) -> int:
    return {"high": 0, "medium": 1, "low": 2}[level]


def _estimate_available_capital(profile: dict[str, Any], metrics: dict[str, Any]) -> float:
    assets = profile.get("assets") or []
    liquid = 0.0
    for a in assets:
        if not isinstance(a, dict):
            continue
        if a.get("liquidity") in ("high", "medium"):
            liquid += float(a.get("value") or 0.0)

    free_cf = float(metrics.get("free_cashflow") or 0.0)
    return max(0.0, liquid + max(0.0, free_cf))


def _min_priority_goal_horizon_months(profile: dict[str, Any]) -> int | None:
    goals = profile.get("goals") or []
    horizons: list[int] = []
    for g in goals:
        if not isinstance(g, dict):
            continue
        if (g.get("priority") or "medium") != "high":
            continue
        h = g.get("horizon_months")
        if isinstance(h, int) and h > 0:
            horizons.append(h)
    if not horizons:
        return None
    return min(horizons)


def _liquidity_compatible(op: InvestmentOpportunity, goal_horizon_months: int | None) -> bool:
    if goal_horizon_months is None:
        return True
    if goal_horizon_months <= 6:
        return op.liquidity_level == "high"
    if goal_horizon_months <= 12:
        return op.liquidity_level in ("high", "medium")
    return True


@dataclass(frozen=True)
class OpportunityMatch:
    opportunity: InvestmentOpportunity
    score: float
    match_reason: str
    score_components: dict[str, float] = field(default_factory=dict)


def evaluate_opportunities(
    *,
    profile: dict[str, Any],
    opportunities: list[InvestmentOpportunity],
    max_results: int = 3,
) -> list[OpportunityMatch]:
    matches, _trace = evaluate_opportunities_with_trace(
        profile=profile,
        opportunities=opportunities,
        max_results=max_results,
    )
    return matches


def evaluate_opportunities_with_trace(
    *,
    profile: dict[str, Any],
    opportunities: list[InvestmentOpportunity],
    max_results: int = 3,
) -> tuple[list[OpportunityMatch], DecisionTrace]:
    metrics = compute_profile_metrics(profile)
    available_capital = _estimate_available_capital(profile, metrics)
    user_risk: RiskLevel = profile.get("risk_tolerance", "medium")
    goal_horizon = _min_priority_goal_horizon_months(profile)
    constraints = detect_constraints(profile, metrics)

    filters_applied = [
        "minimum_capital <= estimated_available_capital",
        "instrument_risk_level <= profile_risk_tolerance",
        "liquidity_level compatible with high-priority goal horizon (if present)",
    ]

    eligible: list[InvestmentOpportunity] = []
    rejected: list[OpportunityRejection] = []
    for op in opportunities:
        reasons: list[str] = []
        if op.minimum_capital > available_capital:
            reasons.append("min_capital_exceeds_available_capital")
        if not _risk_allows(user_risk, op.risk_level):
            reasons.append("risk_exceeds_tolerance")
        if not _liquidity_compatible(op, goal_horizon):
            reasons.append("liquidity_incompatible_with_goal_horizon")
        if reasons:
            rejected.append(
                OpportunityRejection(
                    instrument_id=op.instrument_id,
                    instrument_name=op.instrument_name,
                    reasons=reasons,
                )
            )
        else:
            eligible.append(op)

    matches: list[OpportunityMatch] = []
    for op in eligible:
        capital_score, capital_details = _capital_score(op, available_capital)
        risk_score, risk_details = _risk_score(user_risk, op.risk_level)
        liquidity_score, liquidity_details = _liquidity_score(op, goal_horizon)
        horizon_alignment_score, horizon_details = _horizon_alignment_score(op, profile, goal_horizon)

        weights = {"capital": 0.35, "risk": 0.25, "liquidity": 0.2, "horizon": 0.2}
        total = (
            weights["capital"] * capital_score
            + weights["risk"] * risk_score
            + weights["liquidity"] * liquidity_score
            + weights["horizon"] * horizon_alignment_score
        )
        total = max(0.0, min(1.0, float(total)))

        score_components = {
            "capital_score": capital_score,
            "risk_score": risk_score,
            "liquidity_score": liquidity_score,
            "horizon_alignment_score": horizon_alignment_score,
        }
        match_reason = _build_match_reason(
            op=op,
            available_capital=available_capital,
            goal_horizon=goal_horizon,
            user_risk=user_risk,
            score_components=score_components,
        )
        matches.append(
            OpportunityMatch(
                opportunity=op,
                score=total,
                match_reason=match_reason,
                score_components=score_components,
            )
        )

    matches.sort(key=lambda m: m.score, reverse=True)
    top_matches = matches[:max_results]

    eligible_summaries = [
        OpportunitySummary(
            instrument_id=op.instrument_id,
            instrument_name=op.instrument_name,
            risk_level=op.risk_level,
            liquidity_level=op.liquidity_level,
            minimum_capital=op.minimum_capital,
            market_country=op.market_country,
            currency=op.currency,
            investment_horizon_months={"min_months": op.investment_horizon.min_months, "max_months": op.investment_horizon.max_months},
        )
        for op in eligible
    ]

    breakdown: list[ScoringBreakdown] = []
    for m in matches:
        op = m.opportunity
        breakdown.append(
            ScoringBreakdown(
                instrument_id=op.instrument_id,
                total_score=m.score,
                risk_score=m.score_components["risk_score"],
                liquidity_score=m.score_components["liquidity_score"],
                capital_score=m.score_components["capital_score"],
                horizon_alignment_score=m.score_components["horizon_alignment_score"],
                details={
                    "weights": weights,
                    "available_capital": available_capital,
                    "goal_horizon_months": goal_horizon,
                    "minimum_capital": op.minimum_capital,
                    "user_risk_tolerance": user_risk,
                    "instrument_risk_level": op.risk_level,
                    "liquidity_level": op.liquidity_level,
                    "investment_horizon_min_months": op.investment_horizon.min_months,
                    "investment_horizon_max_months": op.investment_horizon.max_months,
                    "capital_details": capital_details,
                    "risk_details": risk_details,
                    "liquidity_details": liquidity_details,
                    "horizon_details": horizon_details,
                },
            )
        )

    selected_reason = _selected_option_reason(top_matches, breakdown)
    alternatives = [
        {"instrument_id": m.opportunity.instrument_id, "instrument_name": m.opportunity.instrument_name, "score": m.score}
        for m in top_matches[1:3]
    ]

    trace = DecisionTrace(
        input_summary={
            "user_id": profile.get("user_id"),
            "market_country": (profile.get("country") or "").upper() or None,
            "risk_tolerance": user_risk,
            "estimated_available_capital": available_capital,
            "goal_horizon_months": goal_horizon,
            "cashflow": {"monthly_income": metrics["monthly_income"], "monthly_expenses": metrics["monthly_expenses"], "free_cashflow": metrics["free_cashflow"]},
            "constraints_detected": constraints,
        },
        filters_applied=filters_applied,
        eligible_opportunities=eligible_summaries,
        rejected_opportunities=rejected,
        scoring_breakdown=breakdown,
        selected_option_reason=selected_reason,
        alternatives_considered=alternatives,
    )
    return top_matches, trace


def _capital_score(op: InvestmentOpportunity, available_capital: float) -> tuple[float, dict[str, Any]]:
    if available_capital <= 0:
        return 0.0, {"available_capital": available_capital}
    ratio = available_capital / max(1.0, op.minimum_capital)
    score = min(1.0, ratio / 10.0)
    return float(score), {"available_capital": available_capital, "minimum_capital": op.minimum_capital, "ratio": ratio}


def _risk_score(user_risk: RiskLevel, instrument_risk: RiskLevel) -> tuple[float, dict[str, Any]]:
    if user_risk == instrument_risk:
        return 1.0, {"relationship": "equal"}
    if _risk_allows(user_risk, instrument_risk):
        return 0.75, {"relationship": "below_tolerance"}
    return 0.0, {"relationship": "exceeds_tolerance"}


def _liquidity_score(op: InvestmentOpportunity, goal_horizon_months: int | None) -> tuple[float, dict[str, Any]]:
    if not _liquidity_compatible(op, goal_horizon_months):
        return 0.0, {"compatible": False}
    base = {"high": 1.0, "medium": 0.75, "low": 0.4}[op.liquidity_level]
    return float(base), {"compatible": True}


def _horizon_alignment_score(
    op: InvestmentOpportunity, profile: dict[str, Any], goal_horizon_months: int | None
) -> tuple[float, dict[str, Any]]:
    goals = [g for g in (profile.get("goals") or []) if isinstance(g, dict)]
    if not goals:
        return 0.5, {"goal_horizon_months": goal_horizon_months, "goals_present": False}

    def weight(priority: str) -> float:
        return {"high": 1.0, "medium": 0.6, "low": 0.3}.get(priority, 0.6)

    total_w = 0.0
    total_s = 0.0
    per_goal: list[dict[str, Any]] = []
    for g in goals:
        h = g.get("horizon_months")
        if not isinstance(h, int) or h <= 0:
            continue
        pr = str(g.get("priority") or "medium")
        w = weight(pr)
        if op.investment_horizon.min_months <= h <= op.investment_horizon.max_months:
            s = 1.0
            status = "aligned"
        elif h < op.investment_horizon.min_months:
            s = 0.1
            status = "too_illiquid_for_goal_horizon"
        else:
            s = 0.6
            status = "rollover_required_for_goal_horizon"
        total_w += w
        total_s += w * s
        per_goal.append({"goal_name": g.get("name"), "horizon_months": h, "priority": pr, "weight": w, "score": s, "status": status})

    if total_w <= 0:
        return 0.5, {"goal_horizon_months": goal_horizon_months, "goals_present": True, "usable_goals": 0}
    return float(total_s / total_w), {"goal_horizon_months": goal_horizon_months, "goals_present": True, "usable_goals": len(per_goal), "per_goal": per_goal}


def _build_match_reason(
    *,
    op: InvestmentOpportunity,
    available_capital: float,
    goal_horizon: int | None,
    user_risk: RiskLevel,
    score_components: dict[str, float],
) -> str:
    parts: list[str] = []
    parts.append(f"Capital check: minimum {op.minimum_capital:.0f} {op.currency}, estimated available {available_capital:.0f} {op.currency}.")
    parts.append(f"Risk check: profile {user_risk}, instrument {op.risk_level}.")
    if goal_horizon is not None:
        parts.append(
            f"Goal horizon: {goal_horizon} months; instrument horizon {op.investment_horizon.min_months}-{op.investment_horizon.max_months} months; liquidity {op.liquidity_level}."
        )
    else:
        parts.append(f"No high-priority goal horizon provided; using general suitability with liquidity {op.liquidity_level}.")
    parts.append(
        "Scores: "
        f"capital={score_components['capital_score']:.2f}, "
        f"risk={score_components['risk_score']:.2f}, "
        f"liquidity={score_components['liquidity_score']:.2f}, "
        f"horizon={score_components['horizon_alignment_score']:.2f}."
    )
    return " ".join(parts)


def _selected_option_reason(matches: list[OpportunityMatch], breakdown: list[ScoringBreakdown]) -> str:
    if not matches:
        return "No eligible opportunities after applying constraints."
    top = matches[0]
    b = next((x for x in breakdown if x.instrument_id == top.opportunity.instrument_id), None)
    if b is None:
        return f"Selected {top.opportunity.instrument_id} as the highest scoring eligible opportunity."
    return (
        f"Selected {top.opportunity.instrument_name} ({top.opportunity.instrument_id}) because it has the highest total score "
        f"({b.total_score:.2f}) after applying minimum capital, risk tolerance, and liquidity constraints."
    )
