from __future__ import annotations

from app.opportunity_engine.evaluation import evaluate_opportunities
from app.opportunity_engine.repository import OpportunityRepository


def test_opportunity_repository_loads_dataset():
    repo = OpportunityRepository()
    items = repo.load_all()
    assert len(items) >= 5
    assert all(op.instrument_id for op in items)


def test_opportunity_repository_filters_by_country_and_currency():
    repo = OpportunityRepository()
    us_usd = repo.filter(market_country="US", currency="USD")
    mx_mxn = repo.filter(market_country="MX", currency="MXN")
    assert len(us_usd) >= 3
    assert len(mx_mxn) >= 1
    assert all(op.market_country == "US" and op.currency == "USD" for op in us_usd)
    assert all(op.market_country == "MX" and op.currency == "MXN" for op in mx_mxn)


def test_opportunity_scoring_prefers_eligible_matches():
    repo = OpportunityRepository()
    ops = repo.filter(market_country="US", currency="USD")
    profile = {
        "user_id": "u",
        "country": "US",
        "risk_tolerance": "low",
        "cashflow": {"monthly_income": 5000, "monthly_expenses": 3000},
        "assets": [{"name": "Cash", "category": "cash", "value": 5000, "liquidity": "high"}],
        "liabilities": [],
        "goals": [{"name": "Emergency buffer", "target_amount": 6000, "horizon_months": 6, "priority": "high"}],
        "preferences": {"currency": "USD"},
    }
    matches = evaluate_opportunities(profile=profile, opportunities=ops, max_results=3)
    assert len(matches) >= 1
    assert all(m.opportunity.minimum_capital <= 8000 for m in matches)
    assert all(m.opportunity.risk_level in ("low",) for m in matches)
    assert matches == sorted(matches, key=lambda m: m.score, reverse=True)


def test_recommendations_endpoint_includes_opportunity_fields_when_available(test_client):
    profile = {
        "user_id": "opp-user",
        "country": "US",
        "risk_tolerance": "medium",
        "cashflow": {"monthly_income": 7000, "monthly_expenses": 4500},
        "assets": [{"name": "Cash", "category": "cash", "value": 8000, "liquidity": "high"}],
        "liabilities": [],
        "goals": [{"name": "Home down payment", "target_amount": 20000, "horizon_months": 18, "priority": "high"}],
        "preferences": {"currency": "USD"},
    }
    res = test_client.put("/profiles/opp-user", json={"profile": profile})
    assert res.status_code == 200

    res = test_client.post("/recommendations", json={"user_id": "opp-user", "focus": "overview"})
    assert res.status_code == 200
    body = res.json()
    assert isinstance(body["recommendations"], list)

    has_opportunity = any(isinstance(r, dict) and "opportunity" in r for r in body["recommendations"])
    assert has_opportunity

