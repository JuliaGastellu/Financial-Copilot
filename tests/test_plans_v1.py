"""Recorrido de planes versionados, escenarios, adopción, avances y revisión mensual."""
from __future__ import annotations

import threading
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import func, insert, select

from app.data.accounts import utc_now
from app.db.schema import plans
from app.schemas.plans_v1 import PlanResultV1
from tests.v1_payloads import goal_v1, idem, money, profile_v1

THIS_MONTH = date.today().strftime("%Y-%m")


def _setup(client, h, cash: int = 13500) -> dict:
    profile = profile_v1(assets=[{"name": "Main checking", "category": "cash", "liquidity": "high", "value": money(cash)}])
    assert client.put("/v1/profile", json=profile, headers=h).status_code == 200
    goals = {}
    for name, amount, months, priority in (("Down payment", 20000, 18, "high"), ("Car", 9000, 12, "medium"), ("Trip", 3000, 6, "low")):
        res = client.post("/v1/goals", json=goal_v1(name, amount, horizon_months=months, priority=priority), headers=h)
        goals[name] = res.json()["id"]
    return goals


def _plan(client, h, **body):
    res = client.post("/v1/plans", json=body, headers=idem(h))
    assert res.status_code == 201, res.text
    return res.json()


def _goal(result: dict, goal_id: str) -> dict:
    return next(g for g in result["goals"] if g["goal_id"] == goal_id)


def _usd(result: dict) -> dict:
    return next(b for b in result["budgets"] if b["currency"] == "USD")


def test_full_journey_plan_scenario_adoption_progress(client, auth):
    h = auth("journey")
    goals = _setup(client, h)

    # 1. Plan base.
    base = _plan(client, h, as_of="2026-10-03")
    assert (base["version"], base["status"], base["source"]) == (1, "active", "baseline")
    assert Decimal(_usd(base["result"])["monthly"]["allocations"]["goals"]["amount"]) == Decimal("2361.12")

    # 2. Simulo una caída de ingreso de 20%: el plan vigente no cambia.
    res = client.post(
        "/v1/scenarios",
        json={"base_plan_id": base["id"], "name": "Income drops 20%", "income_change": "-0.20"},
        headers=idem(h),
    )
    assert res.status_code == 201, res.text
    scenario = res.json()
    assert scenario["status"] == "simulated"
    usd_cmp = next(c for c in scenario["comparison"] if c["currency"] == "USD")
    assert Decimal(usd_cmp["scenario_monthly_surplus"]["amount"]) == Decimal("1100.00")
    assert Decimal(usd_cmp["goal_contributions_change"]["amount"]) < 0
    assert client.get(f"/v1/plans/{base['id']}", headers=h).json() == base
    current = client.get("/v1/plans/current", headers=h).json()
    assert current["plan"]["id"] == base["id"]
    assert current["freshness"] == {"is_stale": False, "reasons": []}

    # 3. Adopto el escenario de forma explícita: nueva versión, la anterior queda reemplazada.
    res = client.post(f"/v1/scenarios/{scenario['id']}/adoption", headers=idem(h))
    assert res.status_code == 201, res.text
    adopted = res.json()
    assert (adopted["version"], adopted["status"], adopted["source"]) == (2, "active", "scenario")
    assert adopted["source_scenario_id"] == scenario["id"]
    assert adopted["result"] == scenario["result"]
    old = client.get(f"/v1/plans/{base['id']}", headers=h).json()
    assert old["status"] == "superseded" and old["result"] == base["result"]
    assert client.get(f"/v1/scenarios/{scenario['id']}", headers=h).json()["status"] == "adopted"

    # 4. Registro el avance del mes y reviso contra el plan vigente.
    planned_dp = Decimal(_goal(adopted["result"], goals["Down payment"])["monthly_allocation"]["amount"])
    res = client.post(
        "/v1/progress",
        json={"goal_id": goals["Down payment"], "period": THIS_MONTH, "amount": money(str(planned_dp))},
        headers=idem(h),
    )
    assert res.status_code == 201, res.text
    client.post("/v1/progress", json={"goal_id": goals["Car"], "period": THIS_MONTH, "amount": money("10")}, headers=idem(h))
    review = client.get(f"/v1/reviews/{THIS_MONTH}", headers=h).json()
    assert review["plan_id"] == adopted["id"] and review["plan_version"] == 2
    statuses = {g["goal_name"]: g["status"] for g in review["goals"]}
    # Con 20% menos de ingreso, los 1100 de excedente van a la meta prioritaria (requiere 1111.12).
    assert planned_dp == Decimal("1100.00")
    assert statuses["Down payment"] == "met"
    assert statuses["Car"] == "extra"
    assert statuses["Trip"] == "not_planned"
    totals = {t["currency"]: t for t in review["totals"]}
    assert totals["USD"]["planned"]["amount"] == "1100.00" and totals["USD"]["recorded"]["amount"] == "1110.00"
    # El avance registrado cambia las entradas: el plan vigente queda desactualizado.
    assert review["freshness"]["reasons"] == ["inputs_changed"]

    # 5. Reproducción histórica de ambas versiones.
    for plan_id in (base["id"], adopted["id"]):
        repro = client.get(f"/v1/plans/{plan_id}/reproduction", headers=h).json()
        assert repro == {"plan_id": plan_id, "reproducible": True, "identical": True, "reason": None}

    # 6. El historial conserva las dos versiones en orden.
    page = client.get("/v1/plans", headers=h).json()
    assert [p["version"] for p in page["items"]] == [2, 1]


def test_scenario_on_superseded_plan_cannot_be_adopted(client, auth):
    h = auth("stale-scenario")
    _setup(client, h)
    base = _plan(client, h)
    scenario = client.post("/v1/scenarios", json={"base_plan_id": base["id"], "name": "Costs up", "expense_change": "0.1"}, headers=idem(h)).json()
    _plan(client, h)  # una versión nueva reemplaza a la base
    res = client.post(f"/v1/scenarios/{scenario['id']}/adoption", headers=idem(h))
    assert res.status_code == 409
    assert res.json()["code"] == "plan_superseded"
    assert client.get("/v1/plans/current", headers=h).json()["plan"]["version"] == 2


def test_adoption_is_explicit_and_happens_once(client, auth):
    h = auth("adopt-once")
    _setup(client, h)
    base = _plan(client, h)
    scenario = client.post("/v1/scenarios", json={"base_plan_id": base["id"], "name": "S"}, headers=idem(h)).json()
    key = idem(h)
    first = client.post(f"/v1/scenarios/{scenario['id']}/adoption", headers=key)
    replay = client.post(f"/v1/scenarios/{scenario['id']}/adoption", headers=key)
    assert first.status_code == replay.status_code == 201
    assert replay.headers["Idempotent-Replayed"] == "true"
    assert replay.json()["id"] == first.json()["id"]
    again = client.post(f"/v1/scenarios/{scenario['id']}/adoption", headers=idem(h))
    assert again.status_code == 409 and again.json()["code"] == "scenario_already_adopted"
    assert client.delete(f"/v1/scenarios/{scenario['id']}", headers=h).json()["code"] == "scenario_adopted"


# ── Idempotencia ───────────────────────────────────────────────────────────────


def test_plan_creation_is_idempotent(client, auth):
    h = auth("idem-plan")
    _setup(client, h)
    key = idem(h)
    first = client.post("/v1/plans", json={"as_of": "2026-10-03"}, headers=key)
    second = client.post("/v1/plans", json={"as_of": "2026-10-03"}, headers=key)
    assert first.status_code == second.status_code == 201
    assert second.json()["id"] == first.json()["id"]
    assert second.headers.get("Idempotent-Replayed") == "true"
    assert "Idempotent-Replayed" not in first.headers
    assert len(client.get("/v1/plans", headers=h).json()["items"]) == 1

    reused = client.post("/v1/plans", json={"as_of": "2026-10-04"}, headers=key)
    assert reused.status_code == 422 and reused.json()["code"] == "idempotency_key_reused"


@pytest.mark.parametrize("headers,code", [({}, "idempotency_key_required"), ({"Idempotency-Key": "short"}, "idempotency_key_invalid")])
def test_creation_requires_a_valid_idempotency_key(client, auth, headers, code):
    h = auth("idem-missing")
    _setup(client, h)
    res = client.post("/v1/plans", json={}, headers={**h, **headers})
    assert res.status_code == 400 and res.json()["code"] == code


def test_concurrent_retries_create_one_plan(client, auth):
    h = auth("idem-race")
    _setup(client, h)
    key = idem(h)
    results: list[int] = []

    def send() -> None:
        results.append(client.post("/v1/plans", json={}, headers=key).status_code)

    threads = [threading.Thread(target=send) for _ in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert set(results) <= {201, 409}
    assert results.count(201) >= 1
    assert len(client.get("/v1/plans", headers=h).json()["items"]) == 1


def test_idempotency_keys_are_scoped_per_account(client, auth):
    a, b = auth("idem-a"), auth("idem-b")
    _setup(client, a)
    _setup(client, b)
    shared = {"Idempotency-Key": "shared-key-0001"}
    plan_a = client.post("/v1/plans", json={}, headers={**a, **shared}).json()
    plan_b = client.post("/v1/plans", json={}, headers={**b, **shared}).json()
    assert plan_a["id"] != plan_b["id"]


# ── Saldos sin doble conteo ────────────────────────────────────────────────────


def test_contribution_is_counted_once_until_balances_are_updated(client, auth):
    h = auth("double-count")
    goals = _setup(client, h, cash=20000)
    base = _plan(client, h, as_of="2026-10-03")
    trip = goals["Trip"]
    base_trip = _goal(base["result"], trip)
    base_free = Decimal(_usd(base["result"])["current_balances"]["free_after_reserve"]["amount"])

    # Aporte de 500 desde el excedente: suma al ahorro de la meta y al saldo líquido no declarado.
    client.post("/v1/progress", json={"goal_id": trip, "period": THIS_MONTH, "amount": money(500)}, headers=idem(h))
    after = _plan(client, h, as_of="2026-10-03")
    assert Decimal(_goal(after["result"], trip)["saved"]["amount"]) == Decimal(base_trip["saved"]["amount"]) + 500
    assert Decimal(_usd(after["result"])["current_balances"]["free_after_reserve"]["amount"]) == base_free
    snap_goal = next(g for g in after["snapshot"]["goals"] if g["goal_id"] == trip)
    assert snap_goal["contributions_since_declared"]["amount"] == "500.00"
    assert after["snapshot"]["unreconciled_contributions"] == [{"amount": "500.00", "currency": "USD"}]

    # La persona actualiza el ahorro declarado de la meta incluyendo ese aporte: no lo cuento de nuevo.
    goal = client.get(f"/v1/goals/{trip}", headers=h).json()
    updated = goal_v1("Trip", 3000, horizon_months=6, priority="low", saved=money(500))
    assert client.put(f"/v1/goals/{trip}", json=updated, headers=h).status_code == 200
    assert goal["saved"]["amount"] == "0.00"
    reconciled_goal = _plan(client, h, as_of="2026-10-03")
    assert Decimal(_goal(reconciled_goal["result"], trip)["saved"]["amount"]) == Decimal("500.00")

    # La persona actualiza sus saldos: el aporte deja de sumarse como saldo pendiente.
    profile = profile_v1(assets=[{"name": "Main checking", "category": "cash", "liquidity": "high", "value": money(20500)}])
    client.put("/v1/profile", json=profile, headers=h)
    reconciled = _plan(client, h, as_of="2026-10-03")
    assert reconciled["snapshot"]["unreconciled_contributions"] == []
    assert Decimal(_usd(reconciled["result"])["current_balances"]["liquid"]["amount"]) == Decimal("20500.00")


def test_contribution_from_existing_balance_does_not_add_liquidity(client, auth):
    h = auth("existing-balance")
    goals = _setup(client, h, cash=20000)
    base = _plan(client, h, as_of="2026-10-03")
    client.post(
        "/v1/progress",
        json={"goal_id": goals["Trip"], "period": THIS_MONTH, "amount": money(500), "source": "existing_balance"},
        headers=idem(h),
    )
    after = _plan(client, h, as_of="2026-10-03")
    assert after["snapshot"]["unreconciled_contributions"] == []
    assert _usd(after["result"])["current_balances"]["liquid"] == _usd(base["result"])["current_balances"]["liquid"]
    # El dinero cambia de destino dentro de saldos ya declarados: baja el saldo libre.
    assert Decimal(_usd(after["result"])["current_balances"]["free_after_reserve"]["amount"]) == (
        Decimal(_usd(base["result"])["current_balances"]["free_after_reserve"]["amount"]) - 500
    )


# ── Validación y errores ───────────────────────────────────────────────────────


def test_progress_validation_errors_are_useful(client, auth):
    h = auth("progress-errors")
    goals = _setup(client, h)
    gid = goals["Car"]
    cases = [
        ({"goal_id": gid, "period": THIS_MONTH, "amount": money(10, "EUR")}, 422, "currency_mismatch"),
        ({"goal_id": gid, "period": "2999-01", "amount": money(10)}, 422, "future_period"),
        ({"goal_id": "missing", "period": THIS_MONTH, "amount": money(10)}, 404, "not_found"),
    ]
    for body, status, code in cases:
        res = client.post("/v1/progress", json=body, headers=idem(h))
        assert res.status_code == status and res.json()["code"] == code, body
    for body in (
        {"goal_id": gid, "period": "2026-13", "amount": money(10)},
        {"goal_id": gid, "period": THIS_MONTH, "amount": money(0)},
        {"goal_id": gid, "period": THIS_MONTH, "amount": money(10), "user_id": "x"},
    ):
        assert client.post("/v1/progress", json=body, headers=idem(h)).status_code == 422


def test_scenario_validation(client, auth):
    h = auth("scenario-errors")
    _setup(client, h)
    base = _plan(client, h)
    for body in (
        {"base_plan_id": base["id"], "name": "x", "income_change": "-1.5"},
        {"base_plan_id": base["id"], "name": "x", "annual_return": "-1"},
        {"base_plan_id": base["id"], "name": ""},
        {"base_plan_id": base["id"], "name": "x", "income_change": "NaN"},
    ):
        assert client.post("/v1/scenarios", json=body, headers=idem(h)).status_code == 422, body
    res = client.post("/v1/scenarios", json={"base_plan_id": "missing", "name": "x"}, headers=idem(h))
    assert res.status_code == 404


def test_plan_without_profile_and_review_without_plan(client, auth):
    h = auth("empty")
    res = client.post("/v1/plans", json={}, headers=idem(h))
    assert res.status_code == 409 and res.json()["code"] == "profile_required"
    assert client.get("/v1/plans/current", headers=h).status_code == 404
    assert client.get(f"/v1/reviews/{THIS_MONTH}", headers=h).status_code == 404
    assert client.get("/v1/reviews/2026-13", headers=h).status_code == 422


def test_active_plan_cannot_be_deleted_but_superseded_can(client, auth):
    h = auth("delete-plans")
    _setup(client, h)
    first = _plan(client, h)
    res = client.delete(f"/v1/plans/{first['id']}", headers=h)
    assert res.status_code == 409 and res.json()["code"] == "plan_active"
    _plan(client, h)
    assert client.delete(f"/v1/plans/{first['id']}", headers=h).status_code == 204


def test_stale_plan_reasons(client, auth):
    h = auth("stale")
    _setup(client, h)
    _plan(client, h)
    assert client.get("/v1/plans/current", headers=h).json()["freshness"]["is_stale"] is False
    client.post("/v1/goals", json=goal_v1("New goal", 100), headers=h)
    freshness = client.get("/v1/plans/current", headers=h).json()["freshness"]
    assert freshness == {"is_stale": True, "reasons": ["inputs_changed"]}


# ── Paginación ─────────────────────────────────────────────────────────────────


def test_plans_and_progress_are_paginated(client, auth):
    h = auth("pages")
    goals = _setup(client, h)
    for _ in range(5):
        _plan(client, h)
    seen, cursor = [], None
    while True:
        url = "/v1/plans?limit=2" + (f"&cursor={cursor}" if cursor else "")
        page = client.get(url, headers=h).json()
        seen.extend(p["version"] for p in page["items"])
        cursor = page["next_cursor"]
        if not cursor:
            break
    assert seen == [5, 4, 3, 2, 1]
    for _ in range(3):
        client.post("/v1/progress", json={"goal_id": goals["Car"], "period": THIS_MONTH, "amount": money(1)}, headers=idem(h))
    first = client.get("/v1/progress?limit=2", headers=h).json()
    second = client.get(f"/v1/progress?limit=2&cursor={first['next_cursor']}", headers=h).json()
    ids = [e["id"] for e in first["items"] + second["items"]]
    assert len(ids) == len(set(ids)) == 3 and second["next_cursor"] is None
    assert client.get("/v1/plans?limit=51", headers=h).status_code == 422
    bad = client.get("/v1/plans?cursor=not-a-cursor", headers=h)
    assert bad.status_code == 400 and bad.json()["code"] == "invalid_cursor"


# ── Aislamiento ────────────────────────────────────────────────────────────────


def test_b_cannot_touch_a_plans_scenarios_or_progress(client, auth):
    a, b = auth("iso-a"), auth("iso-b")
    goals = _setup(client, a)
    plan = _plan(client, a)
    scenario = client.post("/v1/scenarios", json={"base_plan_id": plan["id"], "name": "A only"}, headers=idem(a)).json()
    entry = client.post("/v1/progress", json={"goal_id": goals["Car"], "period": THIS_MONTH, "amount": money(5)}, headers=idem(a)).json()

    _setup(client, b)
    for method, path, body in (
        ("GET", f"/v1/plans/{plan['id']}", None),
        ("GET", f"/v1/plans/{plan['id']}/reproduction", None),
        ("DELETE", f"/v1/plans/{plan['id']}", None),
        ("GET", f"/v1/scenarios/{scenario['id']}", None),
        ("DELETE", f"/v1/scenarios/{scenario['id']}", None),
        ("DELETE", f"/v1/progress/{entry['id']}", None),
    ):
        res = client.request(method, path, json=body, headers=b)
        assert res.status_code == 404, (method, path)
    assert client.post(f"/v1/scenarios/{scenario['id']}/adoption", headers=idem(b)).status_code == 404
    assert client.post("/v1/scenarios", json={"base_plan_id": plan["id"], "name": "steal"}, headers=idem(b)).status_code == 404
    res = client.post("/v1/progress", json={"goal_id": goals["Car"], "period": THIS_MONTH, "amount": money(5)}, headers=idem(b))
    assert res.status_code == 404
    assert client.get("/v1/scenarios", headers=b).json()["items"] == []
    assert client.get("/v1/progress", headers=b).json()["items"] == []
    assert client.get(f"/v1/progress?goal_id={goals['Car']}", headers=b).json()["items"] == []
    # A conserva todo.
    assert client.get(f"/v1/scenarios/{scenario['id']}", headers=a).status_code == 200
    assert len(client.get("/v1/progress", headers=a).json()["items"]) == 1


# ── Contrato y planes anteriores ───────────────────────────────────────────────


def test_snapshot_is_minimal_and_result_contract_is_closed(client, auth):
    h = auth("minimal")
    _setup(client, h)
    plan = _plan(client, h)
    snapshot = plan["snapshot"]
    assert snapshot["profile"]["country"] is None
    assert [a["name"] for a in snapshot["profile"]["assets"]] == ["asset-1"]
    assert "Main checking" not in str(snapshot)
    with pytest.raises(Exception):
        PlanResultV1.model_validate({**plan["result"], "probability_of_success": 0.7})


def test_legacy_plans_are_readable_but_not_reproducible(client, auth):
    h = auth("legacy-plan")
    user_id = client.get("/v1/me", headers=h).json()["user_id"]
    engine = client.app.state.container.engine
    with engine.begin() as conn:
        conn.execute(
            insert(plans).values(
                id="legacy-plan-id", user_id=user_id, version=1, status="active", source="legacy", as_of=date(2026, 9, 1),
                policy_version="old", engine_version="legacy", snapshot_schema_version=0, inputs_fingerprint="",
                inputs={}, result={}, created_at=utc_now(),
            )
        )
    plan = client.get("/v1/plans/legacy-plan-id", headers=h).json()
    assert plan["reproducible"] is False and plan["snapshot"] is None and plan["result"] is None
    repro = client.get("/v1/plans/legacy-plan-id/reproduction", headers=h).json()
    assert repro["reproducible"] is False
    assert client.get("/v1/plans/current", headers=h).json()["freshness"] == {"is_stale": True, "reasons": ["legacy_plan"]}
    _setup(client, h)
    new = _plan(client, h)
    assert new["version"] == 2
    with engine.connect() as conn:
        actives = conn.execute(select(func.count()).select_from(plans).where(plans.c.user_id == user_id, plans.c.status == "active")).scalar_one()
    assert actives == 1


def test_account_export_and_deletion_cover_new_resources(client, auth):
    h = auth("privacy-plans")
    goals = _setup(client, h)
    plan = _plan(client, h)
    client.post("/v1/scenarios", json={"base_plan_id": plan["id"], "name": "S"}, headers=idem(h))
    client.post("/v1/progress", json={"goal_id": goals["Car"], "period": THIS_MONTH, "amount": money(5)}, headers=idem(h))
    export = client.get("/v1/me/export", headers=h).json()
    assert len(export["scenarios"]) == 1 and len(export["progress_entries"]) == 1
    deleted = client.delete("/v1/me", headers=h).json()["evidence"]["relational_database"]
    assert deleted["deleted"]["scenarios"] == 1 and deleted["deleted"]["progress_entries"] == 1
    assert deleted["deleted"]["idempotency_keys"] == 3
    assert set(deleted["remaining"].values()) == {0}
