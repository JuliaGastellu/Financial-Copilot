from __future__ import annotations

import pytest

from tests.v1_payloads import goal_v1, profile_v1


def test_negative_query_without_token_returns_401(client):
    res = client.post("/v1/knowledge/query", json={"query": "Any advice?"})
    assert res.status_code == 401
    assert res.headers["WWW-Authenticate"].startswith("Bearer")


def test_negative_plan_without_profile_returns_409(client, auth):
    res = client.post("/v1/plans", json={}, headers=auth("missing-profile"))
    assert res.status_code == 409


def test_negative_profile_with_identity_in_body_returns_422(client, auth):
    # Antes comparaba user_id de URL y cuerpo; ahora la identidad no se acepta en el cuerpo.
    res = client.put("/v1/profile", json=profile_v1(user_id="someone-else"), headers=auth("body-user"))
    assert res.status_code == 422


@pytest.mark.parametrize(
    "payload",
    [{}, {"title": "X"}, {"content": "Y"}, {"title": "", "content": "Y"}, {"title": "X", "content": "Doc"}],
)
def test_negative_http_ingest_is_not_available(client, auth, payload):
    # La ingesta por HTTP quedó deshabilitada: el corpus público se carga con un script.
    for headers in ({}, auth("ingest-user")):
        res = client.post("/context/ingest", json=payload, headers=headers)
        assert res.status_code in (404, 405)


def test_negative_profile_get_missing_returns_404(client, auth):
    res = client.get("/v1/profile", headers=auth("no-profile"))
    assert res.status_code == 404


def test_negative_goal_payload_validation(client, auth):
    bad = goal_v1(target={"amount": "-1", "currency": "USD"})
    assert client.post("/v1/goals", json=bad, headers=auth("g")).status_code == 422
    mixed = goal_v1(saved={"amount": "1", "currency": "EUR"})
    assert client.post("/v1/goals", json=mixed, headers=auth("g")).status_code == 422
