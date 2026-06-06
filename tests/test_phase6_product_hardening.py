from __future__ import annotations

import json
import logging


def _create_profile(user_id: str) -> dict:
    return {
        "user_id": user_id,
        "country": "US",
        "risk_tolerance": "medium",
        "cashflow": {"monthly_income": 7000, "monthly_expenses": 4500},
        "assets": [{"name": "Cash", "category": "cash", "value": 8000, "liquidity": "high"}],
        "liabilities": [],
        "goals": [{"name": "Down payment", "target_amount": 20000, "horizon_months": 18, "priority": "high"}],
        "preferences": {"currency": "USD"},
    }


def test_request_id_header_is_present(test_client):
    res = test_client.get("/health")
    assert res.status_code == 200
    assert "X-Request-ID" in res.headers
    assert res.headers["X-Request-ID"]


def test_opportunities_endpoints(test_client):
    res = test_client.get("/opportunities")
    assert res.status_code == 200
    body = res.json()
    assert isinstance(body, list)
    assert len(body) >= 5

    res = test_client.get("/opportunities?market_country=US&currency=USD")
    assert res.status_code == 200
    body = res.json()
    assert all(o["market_country"] == "US" and o["currency"] == "USD" for o in body)


def test_opportunity_match_endpoint_requires_profile_and_returns_trace(test_client):
    res = test_client.get("/opportunities/match/missing")
    assert res.status_code == 404

    res = test_client.put("/profiles/mu", json={"profile": _create_profile("mu")})
    assert res.status_code == 200

    res = test_client.get("/opportunities/match/mu")
    assert res.status_code == 200
    body = res.json()
    assert body["user_id"] == "mu"
    assert isinstance(body["matches"], list)
    assert isinstance(body["decision_trace"], dict)
    assert "scoring_breakdown" in body["decision_trace"]


def test_decision_persistence_and_logging(test_client, caplog):
    caplog.set_level(logging.INFO, logger="ai_financial_copilot")

    res = test_client.put("/profiles/du", json={"profile": _create_profile("du")})
    assert res.status_code == 200

    res = test_client.post("/recommendations", json={"user_id": "du", "focus": "overview"})
    assert res.status_code == 200
    request_id = res.headers.get("X-Request-ID")
    assert request_id
    body = res.json()
    assert "decision_context" in body
    assert isinstance(body["decision_context"], dict)
    assert "decision_id" in body["decision_context"]

    res = test_client.get("/decisions/du")
    assert res.status_code == 200
    decisions = res.json()
    assert isinstance(decisions, list)
    assert len(decisions) >= 1
    assert decisions[0]["user_id"] == "du"
    assert "decision_id" in decisions[0]
    assert "created_at" in decisions[0]
    assert "recommendations" in decisions[0]
    assert "decision_context" in decisions[0]

    events = []
    for rec in caplog.records:
        try:
            payload = json.loads(rec.message)
        except Exception:
            continue
        if payload.get("event") == "recommendation_generated":
            events.append(payload)
    assert events
    assert any(e.get("request_id") == request_id for e in events)

