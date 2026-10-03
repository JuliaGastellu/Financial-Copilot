"""Procedencia de los datos del perfil y creación idempotente de metas."""
from __future__ import annotations

from tests.v1_payloads import goal_v1, idem, money, profile_v1


def _provenance(**overrides: str) -> dict:
    base = {"monthly_income": "reported", "monthly_expenses": "reported", "balances": "reported", "reserve_months": "reported"}
    base.update(overrides)
    return base


def test_estimated_and_unknown_values_become_assumptions_and_missing_data(client, auth):
    h = auth("provenance")
    profile = profile_v1(assets=[], provenance=_provenance(monthly_income="estimated", balances="unknown", reserve_months="unknown"))
    assert client.put("/v1/profile", json=profile, headers=h).status_code == 200
    client.post("/v1/goals", json=goal_v1(), headers=h)
    plan = client.post("/v1/plans", json={}, headers=idem(h)).json()
    result = plan["result"]
    assert "monthly_income_estimated" in result["assumptions"]
    assert {"balances_unknown", "reserve_months_unknown"} <= set(result["missing_data"])
    assert plan["snapshot"]["profile"]["provenance"]["balances"] == "unknown"


def test_unknown_income_or_expenses_block_the_plan(client, auth):
    h = auth("unknown-income")
    profile = profile_v1(cashflows=[{"currency": "USD", "monthly_income": "0", "monthly_expenses": "4500"}], provenance=_provenance(monthly_income="unknown"))
    assert client.put("/v1/profile", json=profile, headers=h).status_code == 200
    res = client.post("/v1/plans", json={}, headers=idem(h))
    assert res.status_code == 409 and res.json()["code"] == "required_data_unknown"


def test_unknown_values_cannot_carry_amounts(client, auth):
    h = auth("unknown-with-value")
    with_assets = profile_v1(provenance=_provenance(balances="unknown"))
    assert client.put("/v1/profile", json=with_assets, headers=h).status_code == 422
    with_reserve = profile_v1(emergency_reserve_months="6", provenance=_provenance(reserve_months="unknown"))
    assert client.put("/v1/profile", json=with_reserve, headers=h).status_code == 422
    bad_value = profile_v1(provenance=_provenance(balances="maybe"))
    assert client.put("/v1/profile", json=bad_value, headers=h).status_code == 422


def test_zero_is_a_reported_value_not_unknown(client, auth):
    h = auth("zero-balance")
    profile = profile_v1(assets=[{"name": "Cash", "category": "cash", "liquidity": "high", "value": money(0)}])
    assert client.put("/v1/profile", json=profile, headers=h).status_code == 200
    client.post("/v1/goals", json=goal_v1(), headers=h)
    result = client.post("/v1/plans", json={}, headers=idem(h)).json()["result"]
    assert "balances_unknown" not in result["missing_data"]
    assert result["budgets"][0]["current_balances"]["liquid"]["amount"] == "0.00"


def test_goal_creation_with_idempotency_key_is_not_duplicated(client, auth):
    h = auth("goal-idem")
    key = idem(h)
    first = client.post("/v1/goals", json=goal_v1("Única"), headers=key)
    second = client.post("/v1/goals", json=goal_v1("Única"), headers=key)
    assert first.status_code == second.status_code == 201
    assert first.json()["id"] == second.json()["id"]
    assert second.headers["Idempotent-Replayed"] == "true"
    assert len(client.get("/v1/goals", headers=h).json()) == 1
    other = client.post("/v1/goals", json=goal_v1("Otra"), headers=key)
    assert other.status_code == 422 and other.json()["code"] == "idempotency_key_reused"


def test_goal_limit_applies_to_idempotent_creation(client, auth, test_settings):
    h = auth("goal-idem-limit")
    object.__setattr__(test_settings, "max_goals_per_user", 1)
    assert client.post("/v1/goals", json=goal_v1("A"), headers=idem(h)).status_code == 201
    res = client.post("/v1/goals", json=goal_v1("B"), headers=idem(h))
    assert res.status_code == 409 and res.json()["code"] == "goal_limit"
