from __future__ import annotations

from app.reasoning.constraints import detect_constraints
from app.reasoning.metrics import compute_profile_metrics


def test_constraint_detection_flags_expected_conditions():
    profile = {
        "user_id": "c",
        "country": "US",
        "risk_tolerance": "low",
        "cashflow": {"monthly_income": 3000, "monthly_expenses": 3500},
        "assets": [{"name": "Cash", "category": "cash", "value": 500, "liquidity": "high"}],
        "liabilities": [{"name": "Card", "balance": 4000, "apr": 22.0, "minimum_payment": 120}],
        "goals": [],
        "preferences": {},
    }
    metrics = compute_profile_metrics(profile)
    constraints = detect_constraints(profile, metrics)
    ids = {c["constraint_id"] for c in constraints}
    assert "negative_cashflow" in ids
    assert "insufficient_emergency_fund" in ids
    assert "high_apr_debt_present" in ids


def test_compute_profile_metrics_includes_debt_ratios():
    profile = {
        "user_id": "metric-user",
        "country": "US",
        "risk_tolerance": "low",
        "cashflow": {"monthly_income": 5000, "monthly_expenses": 3000},
        "assets": [{"name": "Cash", "category": "cash", "value": 6000, "liquidity": "high"}],
        "liabilities": [{"name": "Loan", "balance": 8000, "apr": 10.0, "minimum_payment": 300}],
        "goals": [],
        "preferences": {},
    }
    metrics = compute_profile_metrics(profile)
    assert "debt_to_income_ratio" in metrics
    assert "debt_service_ratio" in metrics
    assert metrics["debt_to_income_ratio"] == 8000 / 5000
    assert metrics["debt_service_ratio"] == 300 / 5000


def test_recommendations_include_decision_context_and_projected_impacts(test_client):
    profile = {
        "user_id": "impact-user",
        "country": "US",
        "risk_tolerance": "medium",
        "cashflow": {"monthly_income": 7000, "monthly_expenses": 4500},
        "assets": [{"name": "Cash", "category": "cash", "value": 8000, "liquidity": "high"}],
        "liabilities": [],
        "goals": [{"name": "Down payment", "target_amount": 20000, "horizon_months": 18, "priority": "high"}],
        "preferences": {"currency": "USD"},
    }
    res = test_client.put("/profiles/impact-user", json={"profile": profile})
    assert res.status_code == 200

    res = test_client.post("/recommendations", json={"user_id": "impact-user", "focus": "overview"})
    assert res.status_code == 200
    body = res.json()

    assert "decision_context" in body
    assert isinstance(body["decision_context"], dict)
    assert "available_capital" in body["decision_context"]
    assert isinstance(body["decision_context"]["available_capital"], (int, float))
    assert "constraints_detected" in body["decision_context"]
    assert isinstance(body["decision_context"]["constraints_detected"], list)

    assert isinstance(body["recommendations"], list) and body["recommendations"]
    for rec in body["recommendations"]:
        assert "impacted_goals" in rec
        assert isinstance(rec["impacted_goals"], list)
        assert "projected_impact" in rec
        if rec["projected_impact"] is not None:
            pi = rec["projected_impact"]
            assert isinstance(pi, dict)
            assert {"time_delta", "confidence", "explanation"}.issubset(set(pi.keys()))

