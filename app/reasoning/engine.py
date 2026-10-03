from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Literal

from app.evaluation.validation import validate_citations
from app.finance.money import Money
from app.finance.planning import FinancialPlan, available_capital
from app.finance.serialization import constraint_to_dict, plan_metrics
from app.opportunity_engine.decision_trace import DecisionTrace
from app.opportunity_engine.evaluation import OpportunityMatch
from app.reasoning.impact import attach_plan_amounts


_sentence_re = re.compile(r"(?<=[.!?])\s+")
_token_re = re.compile(r"[a-zA-Z0-9]{2,}")

# Del modelo de lenguaje solo acepto texto; importes, acciones del plan e indicadores los fija el dominio.
_LLM_TEXT_FIELDS = ("title", "rationale", "actions", "risks")


@dataclass(frozen=True)
class GeneratedQueryResult:
    answer: str
    recommendations: list[dict[str, Any]]
    citations: list[dict[str, Any]]
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
    short: list[str] = []
    for block in context.split("\n\n---\n\n"):
        parts = _sentence_re.split(block.strip())
        for p in parts:
            p = p.strip()
            if len(p) >= 40:
                sentences.append(p)
            elif p:
                short.append(p)
    # Si el contexto solo tiene oraciones cortas, las uso en lugar de responder vacío.
    sentences = sentences or short
    scored = sorted(((s, _keyword_overlap_score(query, s)) for s in sentences), key=lambda x: x[1], reverse=True)
    selected = [s for s, sc in scored if sc > 0][:max_sentences]
    if not selected:
        selected = [s for s, _ in scored[:max_sentences]]
    selected = [s for s in selected if s]
    return " ".join(selected).strip()


def _money_text(value: Money) -> str:
    return f"{format(value.round().amount, 'f')} {value.currency}"


def build_rule_based_recommendations(
    plan: FinancialPlan, signals: dict[str, bool], risk_tolerance: str = "medium"
) -> list[dict[str, Any]]:
    """Derivo recomendaciones del plan. Las acciones con importe usan `plan_action`."""
    base = plan.base_currency
    b = plan.budget(base)
    assert b is not None
    recs: list[dict[str, Any]] = []
    ids = {(c.constraint_id, c.currency) for c in plan.constraints}

    if b.monthly_income.is_zero() and b.monthly_outflow.is_zero():
        recs.append(
            {
                "title": "Stabilize income inputs",
                "rationale": "The plan needs monthly income and expenses; both are zero.",
                "actions": ["Update the profile with net monthly income and monthly expenses.", "List any irregular income sources."],
                "risks": ["Misstated cashflow leads to poor prioritization."],
            }
        )
        return recs

    for budget in plan.budgets:
        if budget.monthly_surplus.is_negative():
            deficit = -budget.monthly_surplus
            recs.append(
                {
                    "title": f"Reduce the cashflow deficit in {budget.currency}",
                    "rationale": (
                        f"Monthly outflows exceed income by {_money_text(deficit)}. "
                        "The plan allocates nothing to reserve, debt or goals in this currency until the deficit is closed."
                    ),
                    "actions": [
                        "Identify the top 3 expense categories and cut at least one recurring cost.",
                        "Create a hard cap for discretionary spending for the next 30 days.",
                        "If feasible, negotiate bills (insurance, telecom) or refinance high-interest debt.",
                    ],
                    "risks": ["Continued deficit can lead to compounding debt costs."],
                }
            )

    if b.reserve_gap.is_positive():
        recs.append(
            {
                "title": "Build an emergency reserve",
                "rationale": (
                    f"The reserve target is {plan.reserve_months} months of outflow ({_money_text(b.reserve_target)}); "
                    f"{_money_text(b.reserve_gap)} is missing. The plan sends the monthly surplus here before goals."
                ),
                "actions": [
                    "Keep the reserve in a liquid, low-volatility account.",
                    "Change the reserve months in the profile if the default does not fit your situation.",
                ],
                "risks": ["Goals receive less while the reserve is being completed."],
                "plan_action": "emergency_reserve",
                "plan_currency": base,
            }
        )

    if b.high_apr_debt_count > 0:
        recs.append(
            {
                "title": "Prioritize high-interest debt payoff",
                "rationale": (
                    f"{b.high_apr_debt_count} debt(s) carry a high annual rate ({_money_text(b.high_apr_debt)} in total). "
                    "After the reserve, the plan pays this debt before funding goals."
                ),
                "actions": ["Keep paying the minimum on every debt.", "Direct the planned extra payment to the highest-rate debt first."],
                "risks": ["Paying debt reduces liquidity; the reserve is funded first for that reason."],
                "plan_action": "high_apr_debt",
                "plan_currency": base,
            }
        )

    base_goals = [g for g in plan.goals if g.currency == base and g.status != "achieved"]
    if base_goals:
        lines = []
        for g in base_goals:
            line = f"{g.name}: {g.status.replace('_', ' ')}, {_money_text(g.monthly_allocation)} per month"
            if g.shortfall_monthly is not None and g.shortfall_monthly.is_positive():
                line += f", short by {_money_text(g.shortfall_monthly)} per month"
            if g.status == "overdue":
                line += "; the target date has passed, set a new one"
            lines.append(line + ".")
        recs.append(
            {
                "title": "Fund your goals with one joint plan",
                "rationale": (
                    "Goals share one budget: current free balance first, then the monthly surplus left after the reserve "
                    "and high-interest debt, by priority and deadline."
                ),
                "actions": lines,
                "risks": ["Goals that show a shortfall need more income, lower expenses, a later date or a smaller target."],
                "plan_action": "goals",
                "plan_currency": base,
            }
        )

    if ("high_debt_service_ratio", base) in ids:
        recs.append(
            {
                "title": "Lower your monthly debt service",
                "rationale": "Minimum payments take a large share of monthly income, so the plan blocks new investments.",
                "actions": [
                    "Review your liabilities and prioritize reducing minimum payments on the highest-cost debts.",
                    "Consider refinancing or consolidating if it lowers the effective rate.",
                ],
                "risks": ["Refinancing may extend repayment and increase total interest if not managed carefully."],
            }
        )

    if ("low_savings_rate", base) in ids:
        recs.append(
            {
                "title": "Increase your savings rate",
                "rationale": "The monthly surplus is below 10% of income, which slows every goal.",
                "actions": [
                    "Review recurring expenses to identify savings opportunities.",
                    "Recalculate the plan after each change to see the new monthly amounts.",
                ],
                "risks": ["Too aggressive cuts can reduce quality of life if they are unsustainable."],
            }
        )

    for c in plan.constraints:
        if c.constraint_id == "goal_currency_without_income":
            recs.append(
                {
                    "title": f"Plan funding for goals in {c.currency}",
                    "rationale": c.effect,
                    "actions": [
                        f"Add income in {c.currency} to the profile if you have it.",
                        "If you convert money, record the rate, date and source before counting it.",
                    ],
                    "risks": ["Mixing currencies without a verified rate hides the real gap."],
                }
            )

    if signals.get("high_rates"):
        recs.append(
            {
                "title": "Use high-rate opportunities for near-term cash",
                "rationale": "Your documents mention elevated rates; cash equivalents can suit short horizons.",
                "actions": [
                    "If you need funds within 12 months, prefer liquid, low-volatility options over equity risk.",
                    "Match goal horizons to liquidity (short-term goals: liquid, long-term goals: diversified).",
                ],
                "risks": ["Locking funds for too long can reduce flexibility."],
            }
        )

    if signals.get("recession_risk"):
        recs.append(
            {
                "title": "Increase resilience to downside scenarios",
                "rationale": "Your documents mention slowdown risk; job and income risk can rise.",
                "actions": ["Consider a longer reserve if income is cyclical.", "Avoid taking on new high-interest liabilities."],
                "risks": ["Overly conservative stance can delay long-term goals."],
            }
        )

    blocked = plan.blocking_constraints(base)
    unassigned = b.unassigned_monthly + b.unassigned_stock
    if risk_tolerance in ("medium", "high") and not blocked and unassigned.is_positive():
        recs.append(
            {
                "title": "Start a disciplined investing plan",
                "rationale": (
                    f"After reserve, debt and goals, {_money_text(b.unassigned_monthly)} per month and "
                    f"{_money_text(b.unassigned_stock)} of current balance remain unassigned."
                ),
                "actions": [
                    "Define a target allocation aligned with risk tolerance and horizon.",
                    "Use periodic contributions to reduce timing sensitivity.",
                ],
                "risks": ["Market drawdowns can occur; avoid investing funds needed in the near term."],
            }
        )

    if not recs:
        recs.append(
            {
                "title": "Maintain and monitor",
                "rationale": "The plan has no open gaps based on the data provided, but circumstances can change.",
                "actions": ["Update the profile monthly.", "Recalculate the plan when income or expenses change."],
                "risks": ["Stale assumptions can lead to delayed actions."],
            }
        )
    return recs


def _plan_recommendations(plan: FinancialPlan, context: str, risk_tolerance: str) -> list[dict[str, Any]]:
    recs = build_rule_based_recommendations(plan, _context_signals(context), risk_tolerance)
    attach_plan_amounts(recs, plan)
    return recs


def _strip_domain_fields(recs: list[Any]) -> list[dict[str, Any]]:
    clean: list[dict[str, Any]] = []
    for r in recs:
        if not isinstance(r, dict):
            continue
        clean.append({k: r[k] for k in _LLM_TEXT_FIELDS if k in r})
    return clean


def generate_query_result(
    *,
    llm: Any | None,
    profile: dict[str, Any],
    plan: FinancialPlan,
    query: str,
    context: str,
    citations: list[dict[str, Any]],
    include_recommendations: bool = True,
) -> GeneratedQueryResult:
    risk = str(profile.get("risk_tolerance") or "medium")
    if llm is None:
        answer = extractive_answer(query, context)
        recs = _plan_recommendations(plan, context, risk) if include_recommendations else []
        return GeneratedQueryResult(
            answer=answer,
            recommendations=recs[:4],
            citations=citations,
            mode="offline",
            fallback_used=True,
            fallback_reason="offline_extractive" if context.strip() else "no_context",
        )

    prompt = (
        "You are an AI financial copilot.\n"
        "Rules:\n"
        "- Use only the provided CONTEXT for factual claims about markets, rates, inflation, or macro conditions.\n"
        "- If context is insufficient, say what is missing and provide general, non-factual guidance.\n"
        "- Do not state amounts that are not in PLAN_METRICS_JSON.\n"
        "- Produce a JSON object with keys: answer (string), recommendations (array).\n"
        "- recommendations items must have: title, rationale, actions (array of strings), risks (array of strings).\n"
        "- Do not invent sources. Citations are handled outside this JSON.\n\n"
        f"USER_PROFILE_JSON:\n{json.dumps(profile, ensure_ascii=False, default=str)}\n\n"
        f"PLAN_METRICS_JSON:\n{json.dumps(plan_metrics(plan), ensure_ascii=False)}\n\n"
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
        if not answer:
            raise ValueError("Missing answer")
        recommendations = _strip_domain_fields(recommendations)
        attach_plan_amounts(recommendations, plan)
        return GeneratedQueryResult(
            answer=answer,
            recommendations=recommendations[:6],
            citations=validate_citations(citations),
            mode="llm",
            fallback_used=False,
            fallback_reason=None,
        )
    except Exception:
        answer = extractive_answer(query, context)
        recs = _plan_recommendations(plan, context, risk) if include_recommendations else []
        return GeneratedQueryResult(
            answer=answer,
            recommendations=recs[:4],
            citations=citations,
            mode="offline",
            fallback_used=True,
            fallback_reason="llm_error",
        )


def generate_recommendations(
    *,
    llm: Any | None,
    profile: dict[str, Any],
    plan: FinancialPlan,
    focus: str,
    context: str,
    citations: list[dict[str, Any]],
    opportunity_matches: list[OpportunityMatch] | None = None,
    opportunity_decision_trace: DecisionTrace | None = None,
) -> GeneratedRecommendations:
    metrics = plan_metrics(plan)
    risk = str(profile.get("risk_tolerance") or "medium")
    opportunity_matches = opportunity_matches or []
    decision_context = _build_decision_context(profile, plan, metrics, opportunity_decision_trace)

    def offline() -> GeneratedRecommendations:
        recs = build_rule_based_recommendations(plan, _context_signals(context), risk)
        if focus != "overview":
            focus_lower = focus.lower()
            recs = [r for r in recs if focus_lower in (r.get("title", "").lower() + " " + r.get("rationale", "").lower())] or recs
        recs = _extend_with_opportunity_recommendations(recs, opportunity_matches, opportunity_decision_trace)
        for r in recs:
            r["sources"] = validate_citations(citations)
        attach_plan_amounts(recs, plan)
        return GeneratedRecommendations(metrics=metrics, recommendations=recs[:8], mode="offline", decision_context=decision_context)

    if llm is None:
        return offline()

    prompt = (
        "You are an AI financial copilot.\n"
        "Task: create actionable, explainable recommendations grounded in the provided CONTEXT.\n"
        "Rules:\n"
        "- Use only the CONTEXT for factual macro/market claims.\n"
        "- Do not state amounts; the plan already sets them.\n"
        "- Output JSON: { recommendations: [ { title, rationale, actions, risks } ] }.\n"
        "- Keep actions concrete and checkable.\n\n"
        f"FOCUS: {focus}\n\n"
        f"USER_PROFILE_JSON:\n{json.dumps(profile, ensure_ascii=False, default=str)}\n\n"
        f"METRICS_JSON:\n{json.dumps(metrics, ensure_ascii=False)}\n\n"
        f"CONTEXT:\n{context}\n"
    )
    try:
        msg = llm.invoke(prompt)
        raw = getattr(msg, "content", str(msg))
        parsed = _safe_parse_json(raw) or {}
        llm_recs = parsed.get("recommendations") or []
        if not isinstance(llm_recs, list):
            llm_recs = []
        llm_recs = _strip_domain_fields(llm_recs)
        if not llm_recs:
            raise ValueError("No recommendations")
        # Las acciones con importe siempre salen del plan; el modelo solo agrega texto.
        plan_recs = [
            r for r in build_rule_based_recommendations(plan, _context_signals(context), risk) if r.get("plan_action")
        ]
        recs = _extend_with_opportunity_recommendations(plan_recs + llm_recs, opportunity_matches, opportunity_decision_trace)
        for r in recs:
            r["sources"] = validate_citations(citations)
        attach_plan_amounts(recs, plan)
        return GeneratedRecommendations(metrics=metrics, recommendations=recs[:10], mode="llm", decision_context=decision_context)
    except Exception:
        return offline()


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
                    "Catalog entries are alternatives to each other: choose at most one and only with unassigned balance.",
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
    plan: FinancialPlan,
    metrics: dict[str, Any],
    opportunity_decision_trace: DecisionTrace | None,
) -> dict[str, Any]:
    reasoning = [f"{c.message} {c.effect}" for c in plan.constraints if c.blocks_new_investment]

    goals_summary = [
        {
            "name": g.name,
            "priority": g.priority,
            "currency": g.currency,
            "status": g.status,
            "target_amount": g.target.to_json(),
            "months_left": g.months_left,
        }
        for g in plan.goals
    ]

    opportunity_summary = None
    if opportunity_decision_trace is not None:
        t = opportunity_decision_trace.model_dump()
        opportunity_summary = {
            "eligible_count": len(t.get("eligible_opportunities") or []),
            "rejected_count": len(t.get("rejected_opportunities") or []),
            "selected_option_reason": t.get("selected_option_reason"),
        }

    capital = available_capital(plan, plan.base_currency)
    return {
        "user_financial_state": {
            "user_id": profile.get("user_id"),
            "country": profile.get("country"),
            "risk_tolerance": profile.get("risk_tolerance"),
            "metrics": metrics,
        },
        "constraints_detected": [constraint_to_dict(c) for c in plan.constraints],
        "available_capital": float(capital.round().amount),
        "available_capital_currency": capital.currency,
        "goals_summary": goals_summary,
        "high_level_reasoning": reasoning,
        "opportunity_engine_summary": opportunity_summary,
        "policy_version": plan.policy_version,
        "as_of": plan.as_of.isoformat(),
    }
