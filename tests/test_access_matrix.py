"""Matriz de acceso: la persona B nunca ve ni modifica recursos de A, y ninguna ruta privada
responde sin token."""
from __future__ import annotations

import json

import pytest
from fastapi.routing import APIRoute

from tests.v1_payloads import goal_v1, money, profile_v1

PUBLIC_ROUTES = {("GET", "/health"), ("GET", "/ready"), ("GET", "/opportunities"), ("GET", "/")}


@pytest.fixture()
def alice(client, auth):
    h = auth("alice")
    assert client.put("/v1/profile", json=profile_v1(), headers=h).status_code == 200
    goal = client.post("/v1/goals", json=goal_v1("Alice secret goal", 4321), headers=h).json()
    plan = client.post("/v1/plans", json={}, headers=h).json()
    return {"headers": h, "goal_id": goal["id"], "plan_id": plan["id"]}


def test_every_non_public_route_requires_a_token(client):
    checked = 0
    for route in client.app.routes:
        if not isinstance(route, APIRoute):
            continue
        for method in route.methods - {"HEAD", "OPTIONS"}:
            if (method, route.path) in PUBLIC_ROUTES:
                continue
            path = route.path.replace("{goal_id}", "x").replace("{plan_id}", "x")
            res = client.request(method, path, json={})
            assert res.status_code == 401, (method, route.path, res.status_code)
            checked += 1
    assert checked >= 14


def test_route_inventory_has_no_identity_parameters(client):
    for route in client.app.routes:
        if isinstance(route, APIRoute):
            assert "user_id" not in route.path and "{user" not in route.path, route.path


@pytest.mark.parametrize(
    "method,path",
    [
        ("PUT", "/profiles/alice"),
        ("GET", "/profiles/alice"),
        ("POST", "/query"),
        ("POST", "/recommendations"),
        ("POST", "/context/ingest"),
        ("GET", "/plans/alice"),
        ("GET", "/opportunities/match/alice"),
        ("GET", "/decisions/alice"),
        ("GET", "/static/app.js"),
        ("GET", "/app.js"),
    ],
)
def test_legacy_routes_are_retired(client, auth, method, path):
    for headers in ({}, auth("alice")):
        res = client.request(method, path, json={"user_id": "alice"}, headers=headers)
        assert res.status_code in (404, 405), (method, path, res.status_code)


def test_b_cannot_read_or_change_a_resources(client, auth, alice):
    b = auth("bob")
    goal, plan = alice["goal_id"], alice["plan_id"]
    assert client.get("/v1/profile", headers=b).status_code == 404
    assert client.get("/v1/goals", headers=b).json() == []
    assert client.get("/v1/plans", headers=b).json() == []
    for method, path, body in (
        ("GET", f"/v1/goals/{goal}", None),
        ("PUT", f"/v1/goals/{goal}", goal_v1("hijack", 1)),
        ("DELETE", f"/v1/goals/{goal}", None),
        ("GET", f"/v1/plans/{plan}", None),
        ("DELETE", f"/v1/plans/{plan}", None),
    ):
        res = client.request(method, path, json=body, headers=b)
        assert res.status_code == 404, (method, path)
        assert res.json() == {"detail": "Not found."}
    # A conserva todo intacto.
    a = alice["headers"]
    assert client.get(f"/v1/goals/{goal}", headers=a).json()["name"] == "Alice secret goal"
    assert client.get(f"/v1/plans/{plan}", headers=a).status_code == 200


def test_b_plan_and_export_never_include_a_data(client, auth, alice):
    b = auth("bob")
    client.put("/v1/profile", json=profile_v1(assets=[]), headers=b)
    plan = client.post("/v1/plans", json={}, headers=b).json()
    assert "Alice secret goal" not in json.dumps(plan)
    export = client.get("/v1/me/export", headers=b)
    assert export.status_code == 200
    text = export.text
    assert "Alice secret goal" not in text and alice["goal_id"] not in text and alice["plan_id"] not in text


def test_b_deletion_does_not_touch_a(client, auth, alice):
    b = auth("bob")
    client.put("/v1/profile", json=profile_v1(), headers=b)
    assert client.delete("/v1/me", headers=b).status_code == 200
    a = alice["headers"]
    assert client.get("/v1/profile", headers=a).status_code == 200
    assert len(client.get("/v1/goals", headers=a).json()) == 1


@pytest.mark.parametrize("field", ["user_id", "owner_id", "sub", "subject"])
def test_identity_fields_in_payload_are_rejected(client, auth, field):
    h = auth("carol")
    assert client.put("/v1/profile", json={**profile_v1(), field: "alice"}, headers=h).status_code == 422
    assert client.post("/v1/goals", json={**goal_v1(), field: "alice"}, headers=h).status_code == 422
    assert client.post("/v1/plans", json={field: "alice"}, headers=h).status_code == 422


def test_identity_headers_and_query_params_are_ignored(client, auth, alice):
    b = auth("bob")
    res = client.get("/v1/goals?user_id=alice", headers={**b, "X-User-Id": "alice", "X-Forwarded-User": "alice"})
    assert res.json() == []


def test_same_subject_from_another_issuer_is_another_account(client, signing_key, alice):
    from app.auth.dev_identity import issue_token
    from tests.conftest import AUDIENCE

    # El verificador solo acepta el emisor configurado: otro emisor con el mismo sub es rechazado.
    token = issue_token(signing_key, issuer="https://other-idp.invalid/", audience=AUDIENCE, subject="alice")
    assert client.get("/v1/goals", headers={"Authorization": f"Bearer {token}"}).status_code == 401


def test_goal_limit_is_enforced(client, auth, test_settings):
    h = auth("dave")
    object.__setattr__(test_settings, "max_goals_per_user", 2)
    for i in range(2):
        assert client.post("/v1/goals", json=goal_v1(f"G{i}", 100 + i), headers=h).status_code == 201
    assert client.post("/v1/goals", json=goal_v1("G3", money(1)["amount"]), headers=h).status_code == 409
