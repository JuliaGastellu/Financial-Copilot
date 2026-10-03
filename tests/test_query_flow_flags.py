"""Retiré /query porque mezclaba el perfil de un user_id del cliente con la consulta.
Mantengo las pruebas del motor de consulta a nivel de función."""
from __future__ import annotations

from datetime import date

from app.finance import plan_for_profile
from app.reasoning.engine import generate_query_result


def _profile() -> dict:
    return {
        "user_id": "q",
        "country": "US",
        "risk_tolerance": "medium",
        "cashflow": {"monthly_income": 5000, "monthly_expenses": 3800},
        "assets": [],
        "liabilities": [],
        "goals": [],
        "preferences": {},
    }


def test_query_default_includes_recommendations_and_has_fallback_fields():
    profile = _profile()
    result = generate_query_result(
        llm=None, profile=profile, plan=plan_for_profile(profile, date(2026, 10, 3)), query="What should I do this month?", context="", citations=[]
    )
    assert len(result.recommendations) > 0
    assert isinstance(result.fallback_used, bool)
    assert result.fallback_reason == "no_context"


def test_query_can_suppress_recommendations():
    profile = _profile()
    result = generate_query_result(
        llm=None,
        profile=profile,
        plan=plan_for_profile(profile, date(2026, 10, 3)),
        query="How do rates affect my decisions?",
        context="Policy rates remain elevated. Inflation eased compared to last year.",
        citations=[],
        include_recommendations=False,
    )
    assert result.answer.strip()
    assert result.recommendations == []
    assert not hasattr(result, "confidence")
