from __future__ import annotations

import json
import logging

from tests.engine_helpers import match
from tests.v1_payloads import goal_v1, profile_v1


def test_request_id_header_is_present(test_client):
    res = test_client.get("/health")
    assert res.status_code == 200
    assert res.headers["X-Request-ID"]


def test_opportunities_endpoints(test_client):
    # El catálogo ilustrativo es público y no contiene datos de personas.
    res = test_client.get("/opportunities")
    assert res.status_code == 200
    assert len(res.json()) >= 5
    res = test_client.get("/opportunities?market_country=US&currency=USD")
    assert all(o["market_country"] == "US" and o["currency"] == "USD" for o in res.json())


def test_opportunity_matching_returns_trace_and_route_is_retired(test_client):
    # /opportunities/match/{user_id} tomaba la identidad de la URL; lo retiré y pruebo el motor.
    assert test_client.get("/opportunities/match/mu").status_code == 404
    profile = {
        "user_id": "mu",
        "country": "US",
        "risk_tolerance": "medium",
        "cashflow": {"monthly_income": 7000, "monthly_expenses": 4500},
        "assets": [{"name": "Cash", "category": "cash", "value": 8000, "liquidity": "high"}],
        "liabilities": [],
        "goals": [{"name": "Down payment", "target_amount": 20000, "horizon_months": 18, "priority": "high"}],
        "preferences": {"currency": "USD"},
    }
    body = match(profile)
    assert "scoring_breakdown" in body["decision_trace"]


def test_plan_persistence_and_logging(client, auth, caplog):
    caplog.set_level(logging.INFO, logger="ai_financial_copilot")
    h = auth("du")
    assert client.put("/v1/profile", json=profile_v1(), headers=h).status_code == 200
    assert client.post("/v1/goals", json=goal_v1(), headers=h).status_code == 201

    res = client.post("/v1/plans", json={}, headers=h)
    assert res.status_code == 201
    request_id = res.headers["X-Request-ID"]
    plan_id = res.json()["id"]

    listed = client.get("/v1/plans", headers=h).json()
    assert [p["id"] for p in listed] == [plan_id]
    assert client.get(f"/v1/plans/{plan_id}", headers=h).json()["plan"] == res.json()["plan"]

    events = []
    for rec in caplog.records:
        try:
            payload = json.loads(rec.message)
        except Exception:
            continue
        if payload.get("event") == "plan_created":
            events.append(payload)
    assert any(e.get("request_id") == request_id for e in events)
    # Los registros no llevan importes ni nombres de metas.
    assert "Down payment" not in caplog.text and "monthly_income" not in caplog.text and "target_amount" not in caplog.text
