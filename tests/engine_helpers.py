"""Ejecuto el motor de recomendaciones sin HTTP. Retiré la ruta pública /recommendations
porque tomaba el user_id del cliente; mantengo las pruebas de su lógica a este nivel."""
from __future__ import annotations

from datetime import date
from typing import Any

from app.finance.adapters import snapshot_from_profile
from app.finance.planning import build_plan, run_scenarios
from app.finance.serialization import plan_to_dict
from app.opportunity_engine.evaluation import evaluate_opportunities_with_trace
from app.opportunity_engine.repository import OpportunityRepository
from app.reasoning.engine import generate_recommendations
from app.schemas.models import RecommendationResponse

AS_OF = date(2026, 10, 3)


def recommend(profile: dict[str, Any], focus: str = "overview", as_of: date = AS_OF) -> dict[str, Any]:
    snapshot = snapshot_from_profile(profile, as_of)
    plan = build_plan(snapshot)
    ops = OpportunityRepository().filter(market_country=(profile.get("country") or "US").upper(), currency=plan.base_currency)
    matches, trace = evaluate_opportunities_with_trace(profile=profile, opportunities=ops, max_results=3, plan=plan)
    result = generate_recommendations(
        llm=None,
        profile=profile,
        plan=plan,
        focus=focus,
        context="",
        citations=[],
        opportunity_matches=matches,
        opportunity_decision_trace=trace,
    )
    result.decision_context["plan"] = plan_to_dict(plan, run_scenarios(snapshot))
    return RecommendationResponse(
        metrics=result.metrics,
        recommendations=result.recommendations,
        mode=result.mode,
        decision_context=result.decision_context,
    ).model_dump(mode="json")


def match(profile: dict[str, Any], as_of: date = AS_OF) -> dict[str, Any]:
    plan = build_plan(snapshot_from_profile(profile, as_of))
    ops = OpportunityRepository().filter(market_country=(profile.get("country") or "US").upper(), currency=plan.base_currency)
    matches, trace = evaluate_opportunities_with_trace(profile=profile, opportunities=ops, max_results=5, plan=plan)
    return {"matches": matches, "decision_trace": trace.model_dump()}
