from __future__ import annotations

from app.opportunity_engine.evaluation import evaluate_opportunities_with_trace
from app.opportunity_engine.repository import OpportunityRepository


def test_decision_trace_structure_and_rejections():
    repo = OpportunityRepository()
    ops = repo.filter(market_country="US", currency="USD")

    profile = {
        "user_id": "trace-user",
        "country": "US",
        "risk_tolerance": "low",
        "cashflow": {"monthly_income": 1950, "monthly_expenses": 1950},
        "assets": [{"name": "Cash", "category": "cash", "value": 0, "liquidity": "high"}],
        "liabilities": [],
        "goals": [{"name": "Rent", "target_amount": 1500, "horizon_months": 3, "priority": "high"}],
        "preferences": {"currency": "USD"},
    }

    matches, trace = evaluate_opportunities_with_trace(profile=profile, opportunities=ops, max_results=3)
    payload = trace.model_dump()

    assert set(payload.keys()) == {
        "input_summary",
        "filters_applied",
        "eligible_opportunities",
        "rejected_opportunities",
        "scoring_breakdown",
        "selected_option_reason",
        "alternatives_considered",
    }
    assert isinstance(payload["input_summary"], dict)
    assert isinstance(payload["filters_applied"], list) and payload["filters_applied"]
    assert isinstance(payload["eligible_opportunities"], list)
    assert isinstance(payload["rejected_opportunities"], list)
    assert isinstance(payload["scoring_breakdown"], list)
    assert isinstance(payload["selected_option_reason"], str) and payload["selected_option_reason"].strip()

    rejected_reason_sets = [set(r["reasons"]) for r in payload["rejected_opportunities"]]
    assert any("risk_exceeds_tolerance" in s for s in rejected_reason_sets)
    assert any("min_capital_exceeds_available_capital" in s for s in rejected_reason_sets)

    for b in payload["scoring_breakdown"]:
        assert set(b.keys()) == {
            "instrument_id",
            "total_score",
            "risk_score",
            "liquidity_score",
            "capital_score",
            "horizon_alignment_score",
            "details",
        }
        assert 0.0 <= b["total_score"] <= 1.0
        assert 0.0 <= b["risk_score"] <= 1.0
        assert 0.0 <= b["liquidity_score"] <= 1.0
        assert 0.0 <= b["capital_score"] <= 1.0
        assert 0.0 <= b["horizon_alignment_score"] <= 1.0
        weights = b["details"]["weights"]
        expected = (
            weights["capital"] * b["capital_score"]
            + weights["risk"] * b["risk_score"]
            + weights["liquidity"] * b["liquidity_score"]
            + weights["horizon"] * b["horizon_alignment_score"]
        )
        assert abs(expected - b["total_score"]) < 1e-8

    assert isinstance(matches, list)


def test_recommendation_includes_decision_trace_and_components(test_client):
    profile = {
        "user_id": "trace-api-user",
        "country": "US",
        "risk_tolerance": "medium",
        "cashflow": {"monthly_income": 7000, "monthly_expenses": 4500},
        "assets": [{"name": "Cash", "category": "cash", "value": 8000, "liquidity": "high"}],
        "liabilities": [],
        "goals": [{"name": "Home down payment", "target_amount": 20000, "horizon_months": 18, "priority": "high"}],
        "preferences": {"currency": "USD"},
    }
    res = test_client.put("/profiles/trace-api-user", json={"profile": profile})
    assert res.status_code == 200

    res = test_client.post("/recommendations", json={"user_id": "trace-api-user", "focus": "overview"})
    assert res.status_code == 200
    body = res.json()

    opportunity_recs = [
        r
        for r in body["recommendations"]
        if isinstance(r, dict) and (r.get("opportunity") is not None)
    ]
    assert opportunity_recs

    rec = opportunity_recs[0]
    assert isinstance(rec.get("match_reason"), str) and "Scores:" in rec["match_reason"]
    assert isinstance(rec.get("score_components"), dict)
    assert set(rec["score_components"].keys()) == {
        "capital_score",
        "risk_score",
        "liquidity_score",
        "horizon_alignment_score",
    }
    assert isinstance(rec.get("decision_trace"), dict)
    assert "rejected_opportunities" in rec["decision_trace"]
    assert "scoring_breakdown" in rec["decision_trace"]
