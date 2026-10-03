"""Contratos del plan y efectos de las restricciones sobre las decisiones."""
from __future__ import annotations

import json
from datetime import date
from decimal import Decimal
from typing import Any

from app.finance import plan_for_profile
from app.reasoning.engine import generate_recommendations
from tests.engine_helpers import match, recommend
from tests.v1_payloads import idem, goal_v1, money, profile_v1


def _legacy_profile(user_id: str, **overrides: Any) -> dict[str, Any]:
    profile: dict[str, Any] = {
        "user_id": user_id,
        "country": "US",
        "currency": "USD",
        "risk_tolerance": "medium",
        "cashflow": {"monthly_income": 7000, "monthly_expenses": 4500},
        "assets": [{"name": "Cash", "category": "cash", "value": 8000, "liquidity": "high"}],
        "liabilities": [],
        "goals": [
            {"name": "Down payment", "target_amount": 20000, "horizon_months": 18, "priority": "high"},
            {"name": "Car", "target_amount": 9000, "horizon_months": 12, "priority": "medium"},
            {"name": "Trip", "target_amount": 3000, "horizon_months": 6, "priority": "low"},
        ],
    }
    profile.update(overrides)
    return profile


def _setup_v1(client, headers, cash: int = 8000) -> None:
    profile = profile_v1(assets=[{"name": "Cash", "category": "cash", "liquidity": "high", "value": money(cash)}])
    assert client.put("/v1/profile", json=profile, headers=headers).status_code == 200
    for goal in (
        goal_v1("Down payment", 20000, horizon_months=18, priority="high"),
        goal_v1("Car", 9000, horizon_months=12, priority="medium"),
        goal_v1("Trip", 3000, horizon_months=6, priority="low"),
    ):
        assert client.post("/v1/goals", json=goal, headers=headers).status_code == 201


def test_plan_endpoint_shape(client, auth) -> None:
    h = auth("p1")
    _setup_v1(client, h)
    res = client.post("/v1/plans", json={"as_of": "2026-10-03"}, headers=idem(h))
    assert res.status_code == 201
    body = res.json()["result"]
    assert body["base_currency"] == "USD"
    usd = body["budgets"][0]
    assert usd["monthly"]["surplus"] == {"amount": "2500.00", "currency": "USD"}
    assert usd["monthly"]["allocated_total"]["amount"] == "2500.00"
    assert len(body["goals"]) == 3
    assert [s["name"] for s in body["scenarios"]] == ["base", "income_down_20", "expenses_up_10"]
    assert "reserve_months_defaulted_to_3" in body["assumptions"]


def test_responses_contain_no_uncalibrated_indicators(client, auth) -> None:
    h = auth("p2")
    _setup_v1(client, h, cash=60000)
    texts = [
        client.post("/v1/plans", json={}, headers=idem(h)).text,
        json.dumps(recommend(_legacy_profile("p2", assets=[{"name": "Cash", "value": 60000, "liquidity": "high"}]))),
    ]
    for text in texts:
        assert "probability" not in text
        assert "confidence" not in text


def test_simultaneous_amounts_never_exceed_the_monthly_surplus() -> None:
    for cash in (0, 8000, 13500, 60000):
        body = recommend(_legacy_profile(f"sum-{cash}", assets=[{"name": "Cash", "value": cash, "liquidity": "high"}]))
        simultaneous = [r for r in body["recommendations"] if r["allocation_kind"] == "simultaneous"]
        assert sum(Decimal(str(r["suggested_amount"] or 0)) for r in simultaneous) <= Decimal("2500")
        goal_recs = [r for r in simultaneous if r["plan_action"] == "goals"]
        if goal_recs:
            assert sum(Decimal(g["monthly_allocation"]["amount"]) for g in goal_recs[0]["impacted_goals"]) <= Decimal("2500")
        for r in body["recommendations"]:
            if r["allocation_kind"] != "simultaneous":
                assert r["suggested_amount"] is None


def test_reserve_gap_blocks_catalog_options() -> None:
    profile = _legacy_profile("p3")
    assert not [r for r in recommend(profile)["recommendations"] if r.get("opportunity")]
    result = match(profile)
    trace = result["decision_trace"]
    assert result["matches"] == []
    assert trace["eligible_opportunities"] == []
    assert all("blocked_by_constraint:insufficient_emergency_fund" in r["reasons"] for r in trace["rejected_opportunities"])
    assert trace["input_summary"]["estimated_available_capital"] == 0.0


def test_deficit_blocks_catalog_options_and_allocations() -> None:
    profile = _legacy_profile(
        "p4", cashflow={"monthly_income": 3000, "monthly_expenses": 3500}, assets=[{"name": "Cash", "value": 90000, "liquidity": "high"}]
    )
    body = recommend(profile)
    assert not [r for r in body["recommendations"] if r.get("opportunity")]
    assert any(r["title"].startswith("Reduce the cashflow deficit") for r in body["recommendations"])
    assert body["decision_context"]["plan"]["budgets"][0]["monthly"]["allocated_total"]["amount"] == "0.00"
    trace = match(profile)["decision_trace"]
    assert all("blocked_by_constraint:negative_cashflow" in r["reasons"] for r in trace["rejected_opportunities"])


def test_non_finite_amounts_and_bad_currencies_are_rejected(client, auth) -> None:
    h = auth("p5")
    raw = json.dumps(profile_v1()).replace('"monthly_income": "7000"', '"monthly_income": NaN')
    res = client.put("/v1/profile", content=raw, headers={**h, "Content-Type": "application/json"})
    assert res.status_code == 422
    assert client.put("/v1/profile", json=profile_v1(currency="DOLLARS"), headers=h).status_code == 422
    duplicate = profile_v1(cashflows=[{"currency": "USD", "monthly_income": "1", "monthly_expenses": "0"}] * 2)
    assert client.put("/v1/profile", json=duplicate, headers=h).status_code == 422


def test_dates_are_persisted_and_overdue_goals_are_reported(client, auth) -> None:
    h = auth("p6")
    assert client.put("/v1/profile", json=profile_v1(), headers=h).status_code == 200
    goal = goal_v1("Late", 5000, target_date="2000-01-01", horizon_months=None)
    created = client.post("/v1/goals", json=goal, headers=h)
    assert created.status_code == 201
    assert created.json()["target_date"] == "2000-01-01"
    plan = client.post("/v1/plans", json={}, headers=idem(h)).json()["result"]
    assert plan["goals"][0]["status"] == "overdue"


def test_legacy_decision_history_route_is_retired(client, auth) -> None:
    # /decisions/{user_id} exponía historial por un identificador de la URL; no lo mantengo.
    assert client.get("/decisions/legacy").status_code == 404
    assert client.get("/decisions/legacy", headers=auth("legacy")).status_code == 404


def test_plan_inputs_allow_reproduction(client, auth) -> None:
    h = auth("p7")
    _setup_v1(client, h)
    first = client.post("/v1/plans", json={"as_of": "2026-10-03"}, headers=idem(h)).json()
    second = client.post("/v1/plans", json={"as_of": "2026-10-03"}, headers=idem(h)).json()
    assert first["id"] != second["id"]
    assert first["result"] == second["result"]
    assert client.get(f"/v1/plans/{first['id']}", headers=h).json()["status"] == "superseded"


class _FakeLlm:
    def __init__(self, payload: dict[str, Any]) -> None:
        self.content = json.dumps(payload)

    def invoke(self, _prompt: str) -> "_FakeLlm":
        return self


def test_language_model_cannot_set_amounts_or_plan_actions() -> None:
    profile = _legacy_profile("llm", assets=[{"name": "Cash", "value": 13500, "liquidity": "high"}])
    plan = plan_for_profile(profile, date(2026, 10, 3))
    llm = _FakeLlm(
        {
            "recommendations": [
                {
                    "title": "Invest everything",
                    "rationale": "r",
                    "actions": ["a"],
                    "risks": [],
                    "plan_action": "goals",
                    "suggested_amount": 999999,
                    "suggested_currency": "USD",
                    "confidence": 0.99,
                }
            ]
        }
    )
    result = generate_recommendations(llm=llm, profile=profile, plan=plan, focus="overview", context="", citations=[])
    assert result.mode == "llm"
    injected = next(r for r in result.recommendations if r["title"] == "Invest everything")
    assert injected["suggested_amount"] is None
    assert injected["allocation_kind"] == "informational"
    assert "confidence" not in injected
    assert "plan_action" not in injected
    goals_rec = next(r for r in result.recommendations if r.get("plan_action") == "goals")
    # 20000/18 = 1111.12 (redondeo hacia arriba), 9000/12 = 750, 3000/6 = 500.
    assert goals_rec["suggested_amount"] == 2361.12
    total = sum(r["suggested_amount"] or 0 for r in result.recommendations if r["allocation_kind"] == "simultaneous")
    assert total <= 2500
