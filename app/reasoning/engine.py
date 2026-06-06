from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Literal

from app.evaluation.validation import clamp_confidence, validate_citations
from app.opportunity_engine.decision_trace import DecisionTrace
from app.opportunity_engine.evaluation import OpportunityMatch
from app.reasoning.constraints import detect_constraints
from app.reasoning.impact import attach_goal_impacts, attach_suggested_amounts, estimate_available_capital
from app.reasoning.metrics import compute_profile_metrics


_sentence_re = re.compile(r"(?<=[.!?])\s+")
_token_re = re.compile(r"[a-zA-Z0-9]{2,}")


@dataclass(frozen=True)
class GeneratedQueryResult:
    answer: str
    recommendations: list[dict[str, Any]]
    citations: list[dict[str, Any]]
    confidence: float
    mode: Literal["llm", "offline"]
    fallback_used: bool
    fallback_reason: str | None


@dataclass(frozen=True)
class GeneratedRecommendations:
    metrics: dict[str, Any]
    recommendations: list[dict[str, Any]]
    mode: Literal["llm", "offline"]
    decision_context: dict[str, Any]


def _safe_parse_json(text: str) -> dict[str, Any] | None:
    try:
        return json.loads(text)
    except Exception:
        pass
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    try:
        return json.loads(text[start : end + 1])
    except Exception:
        return None


def _context_signals(context: str) -> dict[str, bool]:
    lower = context.lower()
    return {
        "high_rates": any(k in lower for k in ["policy rate", "high interest", "rates are high", "rate hikes", "tightening"]),
        "inflation": "inflation" in lower,
        "recession_risk": any(k in lower for k in ["recession", "slowdown", "unemployment rising"]),
        "equities_volatility": any(k in lower for k in ["volatility", "drawdown", "market sell-off"]),
    }


def _keyword_overlap_score(query: str, sentence: str) -> float:
    q = set(_token_re.findall(query.lower()))
    if not q:
        return 0.0
    s = set(_token_re.findall(sentence.lower()))
    return len(q.intersection(s)) / len(q)


def extractive_answer(query: str, context: str, max_sentences: int = 5) -> str:
    if not context.strip():
        return (
            "I do not have enough grounded context to answer reliably. "
            "Ingest relevant economic notes or documents, then retry the same question."
        )
    sentences: list[str] = []
    for block in context.split("\n\n---\n\n"):
        parts = _sentence_re.split(block.strip())
        for p in parts:
            p = p.strip()
            if len(p) >= 40:
                sentences.append(p)
    scored = sorted(((s, _keyword_overlap_score(query, s)) for s in sentences), key=lambda x: x[1], reverse=True)
    selected = [s for s, sc in scored if sc > 0][:max_sentences]
    if not selected:
        selected = [s for s, _ in scored[:max_sentences]]
    selected = [s for s in selected if s]
    return " ".join(selected).strip()


def build_rule_based_recommendations(profile: dict[str, Any], signals: dict[str, bool]) -> list[dict[str, Any]]:
    metrics = compute_profile_metrics(profile)
    income = metrics["monthly_income"]
    expenses = metrics["monthly_expenses"]
    free_cf = metrics["free_cashflow"]
    emergency = metrics["emergency_fund_months"]
    high_apr_debt_count = metrics["high_apr_debt_count"]
    savings_rate = metrics.get("savings_rate") or 0.0
    debt_to_income = metrics.get("debt_to_income_ratio") or 0.0
    debt_service_ratio = metrics.get("debt_service_ratio") or 0.0
    risk = profile.get("risk_tolerance", "medium")

    recs: list[dict[str, Any]] = []

    if income <= 0:
        recs.append(
            {
                "title": "Stabilize income inputs",
                "rationale": "Recommendations depend on a reliable income estimate.",
                "actions": ["Update the profile with net monthly income and essential expenses.", "List any irregular income sources."],
                "risks": ["Misstated cashflow leads to poor prioritization."],
            }
        )
        return recs

    if free_cf < 0:
        recs.append(
            {
                "title": "Reduce the cashflow deficit",
                "rationale": "Spending exceeds income, which increases borrowing risk and blocks investing.",
                "actions": [
                    "Identify the top 3 expense categories and cut at least one recurring cost.",
                    "Create a hard cap for discretionary spending for the next 30 days.",
                    "If feasible, negotiate bills (insurance, telecom) or refinance high-interest debt.",
                ],
                "risks": ["Continued deficit can lead to compounding debt costs."],
            }
        )
    else:
        recs.append(
            {
                "title": "Allocate free cashflow intentionally",
                "rationale": "A stable monthly surplus enables structured saving, debt payoff, and long-term investing.",
                "actions": [
                    f"Automate a monthly transfer of {max(0.0, free_cf * 0.5):.0f} into savings or goal buckets.",
                    "Split the remaining surplus between debt payoff and long-term investing based on APR and goals.",
                ],
                "risks": ["Unallocated surplus is likely to be consumed by lifestyle drift."],
            }
        )

    if savings_rate < 0.1 and free_cf > 0:
        recs.append(
            {
                "title": "Increase your savings rate",
                "rationale": "A savings rate below 10% may delay long-term goals and reduce financial resilience.",
                "actions": [
                    "Review recurring expenses to identify savings opportunities.",
                    "Increase the portion of surplus allocated to savings and goal contributions.",
                ],
                "risks": ["Too aggressive cuts can reduce quality of life if they are unsustainable."],
            }
        )

    if emergency is None or emergency < 3:
        months_label = "3–6" if emergency is None or emergency < 3 else "6"
        recs.append(
            {
                "title": "Build an emergency fund",
                "rationale": f"A buffer of {months_label} months of essential expenses reduces the need for high-cost debt.",
                "actions": [
                    "Set a target of at least 3 months of essential expenses as a first milestone.",
                    "Keep the emergency fund in a liquid, low-volatility vehicle (cash equivalents).",
                ],
                "risks": ["Insufficient liquidity forces asset sales or borrowing during shocks."],
            }
        )

    if debt_to_income >= 0.4 and free_cf >= 0:
        recs.append(
            {
                "title": "Improve your debt-to-income profile",
                "rationale": "A high liability burden relative to income can reduce credit flexibility and investment capacity.",
                "actions": [
                    "Focus extra cashflow on paying down high-balance or high-cost liabilities.",
                    "Avoid taking on new credit until the ratio is more comfortable.",
                ],
                "risks": ["Paying down debt too quickly may temporarily reduce liquidity."],
            }
        )

    if debt_service_ratio >= 0.2 and free_cf >= 0:
        recs.append(
            {
                "title": "Lower your monthly debt service",
                "rationale": "A large share of income tied to debt payments can reduce financial flexibility.",
                "actions": [
                    "Review your liabilities and prioritize reducing minimum payments on the highest-cost debts.",
                    "Consider refinancing or consolidating if it lowers the effective APR.",
                ],
                "risks": ["Refinancing may extend repayment and increase total interest if not managed carefully."],
            }
        )

    if high_apr_debt_count > 0:
        strategy = "debt avalanche (highest APR first)"
        recs.append(
            {
                "title": "Prioritize high-interest debt payoff",
                "rationale": "Debt with double-digit APR often dominates risk-adjusted returns.",
                "actions": ["List each liability with APR and minimum payment.", f"Pay minimums on all debts, then direct extra cash to {strategy}."],
                "risks": ["Aggressive payoff may reduce liquidity if emergency fund is too small."],
            }
        )

    if signals.get("high_rates"):
        recs.append(
            {
                "title": "Use high-rate opportunities for near-term cash",
                "rationale": "When risk-free rates are elevated, cash equivalents can be attractive for short horizons.",
                "actions": [
                    "If you need funds within 12 months, consider high-yield cash equivalents instead of taking equity risk.",
                    "Match goal horizons to liquidity (short-term goals: liquid, long-term goals: diversified).",
                ],
                "risks": ["Locking funds for too long can reduce flexibility."],
            }
        )

    if risk in ("medium", "high") and free_cf > 0 and (emergency is None or emergency >= 3):
        recs.append(
            {
                "title": "Start a disciplined investing plan",
                "rationale": "A rules-based contribution schedule reduces timing risk and supports long-term goals.",
                "actions": [
                    "Define a target allocation aligned with risk tolerance and horizon.",
                    "Use periodic contributions (for example, monthly) to reduce timing sensitivity.",
                ],
                "risks": ["Market drawdowns can occur; avoid investing funds needed in the near term."],
            }
        )

    if signals.get("recession_risk"):
        recs.append(
            {
                "title": "Increase resilience to downside scenarios",
                "rationale": "During slowdowns, job and income risk can rise.",
                "actions": ["Increase the emergency fund target toward 6 months if income is cyclical.", "Avoid taking on new high-APR liabilities."],
                "risks": ["Overly conservative stance can delay long-term goals."],
            }
        )

    if not recs:
        recs.append(
            {
                "title": "Maintain and monitor",
                "rationale": "The profile looks stable based on provided data, but context can change.",
                "actions": ["Update the profile monthly.", "Ingest new macro and market notes when conditions change."],
                "risks": ["Stale assumptions can lead to delayed actions."],
            }
        )
    return recs


def generate_query_result(
    *,
    llm: Any | None,
    profile: dict[str, Any],
    query: str,
    context: str,
    citations: list[dict[str, Any]],
    include_recommendations: bool = True,
) -> GeneratedQueryResult:
    if llm is None:
        answer = extractive_answer(query, context)
        recs = build_rule_based_recommendations(profile, _context_signals(context)) if include_recommendations else []
        return GeneratedQueryResult(
            answer=answer,
            recommendations=recs[:4],
            citations=citations,
            confidence=0.35 if context.strip() else 0.15,
            mode="offline",
            fallback_used=True,
            fallback_reason="offline_extractive" if context.strip() else "no_context",
        )

    prompt = (
        "You are an AI financial copilot.\n"
        "Rules:\n"
        "- Use only the provided CONTEXT for factual claims about markets, rates, inflation, or macro conditions.\n"
        "- If context is insufficient, say what is missing and provide general, non-factual guidance.\n"
        "- Produce a JSON object with keys: answer (string), recommendations (array), confidence (number 0..1).\n"
        "- recommendations items must have: title, rationale, actions (array of strings), risks (array of strings).\n"
        "- Do not invent sources. Citations are handled outside this JSON.\n\n"
        f"USER_PROFILE_JSON:\n{json.dumps(profile, ensure_ascii=False)}\n\n"
        f"QUESTION:\n{query}\n\n"
        f"CONTEXT:\n{context}\n"
    )
    try:
        msg = llm.invoke(prompt)
        raw = getattr(msg, "content", str(msg))
        parsed = _safe_parse_json(raw) or {}
        answer = str(parsed.get("answer") or "").strip()
        recommendations = (parsed.get("recommendations") or []) if include_recommendations else []
        if not isinstance(recommendations, list):
            recommendations = []
        confidence = clamp_confidence(parsed.get("confidence"))
        if not answer:
            raise ValueError("Missing answer")
        return GeneratedQueryResult(
            answer=answer,
            recommendations=recommendations[:6],
            citations=validate_citations(citations),
            confidence=confidence,
            mode="llm",
            fallback_used=False,
            fallback_reason=None,
        )
    except Exception:
        answer = extractive_answer(query, context)
        recs = build_rule_based_recommendations(profile, _context_signals(context)) if include_recommendations else []
        return GeneratedQueryResult(
            answer=answer,
            recommendations=recs[:4],
            citations=citations,
            confidence=0.3 if context.strip() else 0.12,
            mode="offline",
            fallback_used=True,
            fallback_reason="llm_error",
        )


def generate_recommendations(
    *,
    llm: Any | None,
    profile: dict[str, Any],
    focus: str,
    context: str,
    citations: list[dict[str, Any]],
    opportunity_matches: list[OpportunityMatch] | None = None,
    opportunity_decision_trace: DecisionTrace | None = None,
) -> GeneratedRecommendations:
    metrics = compute_profile_metrics(profile)
    constraints = detect_constraints(profile, metrics)
    available_capital = estimate_available_capital(profile, metrics)
    opportunity_matches = opportunity_matches or []
    if llm is None:
        recs = build_rule_based_recommendations(profile, _context_signals(context))
        if focus != "overview":
            focus_lower = focus.lower()
            recs = [r for r in recs if focus_lower in (r.get("title", "").lower() + " " + r.get("rationale", "").lower())] or recs
        recs = _extend_with_opportunity_recommendations(recs, opportunity_matches, opportunity_decision_trace)
        for r in recs:
            r["sources"] = validate_citations(citations)
        attach_goal_impacts(profile=profile, metrics=metrics, recommendations=recs)
        attach_suggested_amounts(profile=profile, metrics=metrics, recommendations=recs, available_capital=available_capital)
        return GeneratedRecommendations(
            metrics=metrics,
            recommendations=recs[:6],
            mode="offline",
            decision_context=_build_decision_context(profile, metrics, constraints, available_capital, opportunity_decision_trace),
        )

    prompt = (
        "You are an AI financial copilot.\n"
        "Task: create actionable, explainable recommendations grounded in the provided CONTEXT.\n"
        "Rules:\n"
        "- Use only the CONTEXT for factual macro/market claims.\n"
        "- Output JSON: { recommendations: [ { title, rationale, actions, risks } ] }.\n"
        "- Keep actions concrete and checkable.\n\n"
        f"FOCUS: {focus}\n\n"
        f"USER_PROFILE_JSON:\n{json.dumps(profile, ensure_ascii=False)}\n\n"
        f"METRICS_JSON:\n{json.dumps(metrics, ensure_ascii=False)}\n\n"
        f"CONTEXT:\n{context}\n"
    )
    try:
        msg = llm.invoke(prompt)
        raw = getattr(msg, "content", str(msg))
        parsed = _safe_parse_json(raw) or {}
        recs = parsed.get("recommendations") or []
        if not isinstance(recs, list):
            recs = []
        recs = _extend_with_opportunity_recommendations(recs, opportunity_matches, opportunity_decision_trace)
        for r in recs:
            if isinstance(r, dict):
                r["sources"] = validate_citations(citations)
        if not recs:
            raise ValueError("No recommendations")
        attach_goal_impacts(profile=profile, metrics=metrics, recommendations=recs)
        attach_suggested_amounts(profile=profile, metrics=metrics, recommendations=recs, available_capital=available_capital)
        return GeneratedRecommendations(
            metrics=metrics,
            recommendations=recs[:8],
            mode="llm",
            decision_context=_build_decision_context(profile, metrics, constraints, available_capital, opportunity_decision_trace),
        )
    except Exception:
        recs = build_rule_based_recommendations(profile, _context_signals(context))
        recs = _extend_with_opportunity_recommendations(recs, opportunity_matches, opportunity_decision_trace)
        for r in recs:
            r["sources"] = validate_citations(citations)
        attach_goal_impacts(profile=profile, metrics=metrics, recommendations=recs)
        attach_suggested_amounts(profile=profile, metrics=metrics, recommendations=recs, available_capital=available_capital)
        return GeneratedRecommendations(
            metrics=metrics,
            recommendations=recs[:6],
            mode="offline",
            decision_context=_build_decision_context(profile, metrics, constraints, available_capital, opportunity_decision_trace),
        )


def _extend_with_opportunity_recommendations(
    base_recommendations: list[dict[str, Any]],
    matches: list[OpportunityMatch],
    decision_trace: DecisionTrace | None,
    max_additional: int = 2,
) -> list[dict[str, Any]]:
    if not matches:
        return base_recommendations
    out = list(base_recommendations)
    trace_payload = decision_trace.model_dump() if decision_trace is not None else None
    for m in matches[:max_additional]:
        op = m.opportunity
        out.append(
            {
                "title": f"Consider: {op.instrument_name}",
                "rationale": m.match_reason,
                "actions": [
                    f"Verify access requirements: {', '.join(op.access_requirements) if op.access_requirements else 'None listed'}.",
                    f"Confirm liquidity level ({op.liquidity_level}) and horizon ({op.investment_horizon.min_months}-{op.investment_horizon.max_months} months) fit your goals.",
                    "Decide an amount that preserves an emergency buffer and respects minimum capital requirements.",
                ],
                "risks": [
                    f"Risk level: {op.risk_level}. Expected returns are uncertain and may be negative over short periods.",
                    "This is a local dataset example, not live market data.",
                ],
                "opportunity": {
                    "instrument_id": op.instrument_id,
                    "instrument_name": op.instrument_name,
                    "asset_class": op.asset_class,
                    "market_country": op.market_country,
                    "currency": op.currency,
                    "minimum_capital": op.minimum_capital,
                    "liquidity_level": op.liquidity_level,
                    "expected_return_range": op.expected_return_range.model_dump(),
                    "risk_level": op.risk_level,
                    "investment_horizon": op.investment_horizon.model_dump(),
                    "access_requirements": op.access_requirements,
                    "source_name": op.source_name,
                    "source_url": str(op.source_url),
                    "last_updated_at": op.last_updated_at.isoformat(),
                },
                "match_reason": m.match_reason,
                "match_score": m.score,
                "score_components": m.score_components,
                "decision_trace": trace_payload,
            }
        )
    return out


def _build_decision_context(
    profile: dict[str, Any],
    metrics: dict[str, Any],
    constraints: list[dict[str, Any]],
    available_capital: float,
    opportunity_decision_trace: DecisionTrace | None,
) -> dict[str, Any]:
    reasoning: list[str] = []
    if any(c.get("constraint_id") == "negative_cashflow" for c in constraints):
        reasoning.append("Negative free cashflow detected; prioritize deficit reduction before committing new capital.")
    if any(c.get("constraint_id") == "insufficient_emergency_fund" for c in constraints):
        reasoning.append("Emergency fund coverage is below target; preserve liquidity before taking additional risk.")
    if any(c.get("constraint_id") == "high_apr_debt_present" for c in constraints):
        reasoning.append("High-interest debt detected; debt payoff may dominate risk-adjusted returns.")

    goals = [g for g in (profile.get("goals") or []) if isinstance(g, dict)]
    goals_summary = [
        {"name": g.get("name"), "priority": g.get("priority"), "target_amount": g.get("target_amount"), "horizon_months": g.get("horizon_months")}
        for g in goals[:5]
    ]

    opportunity_summary = None
    if opportunity_decision_trace is not None:
        t = opportunity_decision_trace.model_dump()
        opportunity_summary = {
            "eligible_count": len(t.get("eligible_opportunities") or []),
            "rejected_count": len(t.get("rejected_opportunities") or []),
            "selected_option_reason": t.get("selected_option_reason"),
        }

    return {
        "user_financial_state": {
            "user_id": profile.get("user_id"),
            "country": profile.get("country"),
            "risk_tolerance": profile.get("risk_tolerance"),
            "metrics": metrics,
        },
        "constraints_detected": constraints,
        "available_capital": available_capital,
        "goals_summary": goals_summary,
        "high_level_reasoning": reasoning,
        "opportunity_engine_summary": opportunity_summary,
    }
