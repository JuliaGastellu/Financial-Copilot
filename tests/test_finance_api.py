"""Contratos de API del plan y efectos de las restricciones sobre las decisiones."""
from __future__ import annotations

import json
from datetime import date
from decimal import Decimal
from typing import Any

from app.finance import plan_for_profile
from app.reasoning.engine import generate_recommendations
from app.services.compat import strip_uncalibrated_indicators


def _profile(user_id: str, **overrides: Any) -> dict[str, Any]:
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


def _put(client, profile: dict[str, Any]) -> None:
    res = client.put(f"/profiles/{profile['user_id']}", json={"profile": profile})
    assert res.status_code == 200, res.text


def _recommend(client, user_id: str) -> dict[str, Any]:
    res = client.post("/recommendations", json={"user_id": user_id, "focus": "overview"})
    assert res.status_code == 200, res.text
    return res.json()


def test_plan_endpoint_shape_and_missing_profile(test_client) -> None:
    assert test_client.get("/plans/nobody").status_code == 404
    _put(test_client, _profile("p1"))
    res = test_client.get("/plans/p1")
    assert res.status_code == 200
    body = res.json()
    assert body["base_currency"] == "USD"
    assert body["policy_version"]
    usd = body["budgets"][0]
    assert usd["monthly"]["surplus"] == {"amount": "2500.00", "currency": "USD"}
    assert usd["monthly"]["allocated_total"]["amount"] == "2500.00"
    assert len(body["goals"]) == 3
    assert [s["name"] for s in body["scenarios"]] == ["base", "income_down_20", "expenses_up_10"]
    assert "reserve_months_defaulted_to_3" in body["assumptions"]


def test_responses_contain_no_uncalibrated_indicators(test_client) -> None:
    _put(test_client, _profile("p2", assets=[{"name": "Cash", "value": 60000, "liquidity": "high"}]))
    for text in (json.dumps(_recommend(test_client, "p2")), test_client.get("/plans/p2").text):
        assert "probability" not in text
        assert "confidence" not in text


def test_simultaneous_amounts_never_exceed_the_monthly_surplus(test_client) -> None:
    for cash in (0, 8000, 13500, 60000):
        user = f"sum-{cash}"
        _put(test_client, _profile(user, assets=[{"name": "Cash", "value": cash, "liquidity": "high"}]))
        body = _recommend(test_client, user)
        simultaneous = [r for r in body["recommendations"] if r["allocation_kind"] == "simultaneous"]
        total = sum(Decimal(str(r["suggested_amount"] or 0)) for r in simultaneous)
        assert total <= Decimal("2500")
        goal_recs = [r for r in simultaneous if r["plan_action"] == "goals"]
        if goal_recs:
            assert sum(Decimal(g["monthly_allocation"]["amount"]) for g in goal_recs[0]["impacted_goals"]) <= Decimal("2500")
        for r in body["recommendations"]:
            if r["allocation_kind"] != "simultaneous":
                assert r["suggested_amount"] is None


def test_reserve_gap_blocks_catalog_options(test_client) -> None:
    _put(test_client, _profile("p3"))
    body = _recommend(test_client, "p3")
    assert not [r for r in body["recommendations"] if r.get("opportunity")]
    res = test_client.get("/opportunities/match/p3")
    trace = res.json()["decision_trace"]
    assert res.json()["matches"] == []
    assert trace["eligible_opportunities"] == []
    assert all("blocked_by_constraint:insufficient_emergency_fund" in r["reasons"] for r in trace["rejected_opportunities"])
    assert trace["input_summary"]["estimated_available_capital"] == 0.0


def test_deficit_blocks_catalog_options_and_allocations(test_client) -> None:
    _put(test_client, _profile("p4", cashflow={"monthly_income": 3000, "monthly_expenses": 3500}, assets=[{"name": "Cash", "value": 90000, "liquidity": "high"}]))
    body = _recommend(test_client, "p4")
    assert not [r for r in body["recommendations"] if r.get("opportunity")]
    assert any(r["title"].startswith("Reduce the cashflow deficit") for r in body["recommendations"])
    plan = body["decision_context"]["plan"]
    assert plan["budgets"][0]["monthly"]["allocated_total"]["amount"] == "0.00"
    trace = test_client.get("/opportunities/match/p4").json()["decision_trace"]
    assert all("blocked_by_constraint:negative_cashflow" in r["reasons"] for r in trace["rejected_opportunities"])


def test_non_finite_amounts_and_bad_currencies_are_rejected(test_client) -> None:
    raw = json.dumps({"profile": _profile("p5")}).replace('"monthly_income": 7000', '"monthly_income": NaN')
    res = test_client.put("/profiles/p5", content=raw, headers={"Content-Type": "application/json"})
    assert res.status_code == 422
    res = test_client.put("/profiles/p5", json={"profile": _profile("p5", currency="DOLLARS")})
    assert res.status_code == 422
    res = test_client.put(
        "/profiles/p5",
        json={"profile": _profile("p5", additional_cashflows=[{"currency": "USD", "monthly_income": 1}])},
    )
    assert res.status_code == 422


def test_dates_are_persisted_and_overdue_goals_are_reported(test_client) -> None:
    goals = [{"name": "Late", "target_amount": 5000, "target_date": "2000-01-01", "priority": "high"}]
    _put(test_client, _profile("p6", goals=goals))
    assert test_client.get("/profiles/p6").json()["profile"]["goals"][0]["target_date"] == "2000-01-01"
    plan = test_client.get("/plans/p6").json()
    assert plan["goals"][0]["status"] == "overdue"


def test_legacy_decisions_are_read_without_uncalibrated_indicators(test_client) -> None:
    decisions = test_client.app.state.container.decisions
    decisions.create(
        user_id="legacy",
        decision={
            "recommendations": [
                {
                    "title": "Old",
                    "impacted_goals": [{"goal_name": "G", "probability_of_success": 0.7, "confidence": 0.9}],
                    "projected_impact": {"time_delta": -2, "confidence": 0.8, "explanation": "x"},
                }
            ],
            "decision_context": {"available_capital": 10500.0},
            "mode": "offline",
        },
    )
    body = test_client.get("/decisions/legacy").json()
    text = json.dumps(body[0]["recommendations"])
    assert "probability_of_success" not in text and "confidence" not in text
    assert body[0]["decision_context"]["legacy_indicators_removed"] == ["confidence", "probability_of_success"]
    assert body[0]["recommendations"][0]["projected_impact"]["time_delta"] == -2


def test_strip_is_a_no_op_for_current_records() -> None:
    record = {"recommendations": [{"title": "x"}], "decision_context": {"a": 1}}
    assert strip_uncalibrated_indicators(record) == record


class _FakeLlm:
    def __init__(self, payload: dict[str, Any]) -> None:
        self.content = json.dumps(payload)

    def invoke(self, _prompt: str) -> "_FakeLlm":
        return self


def test_language_model_cannot_set_amounts_or_plan_actions() -> None:
    profile = _profile("llm", assets=[{"name": "Cash", "value": 13500, "liquidity": "high"}])
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
