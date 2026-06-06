from __future__ import annotations

import pytest


def _create_profile(user_id: str) -> dict:
    return {
        "user_id": user_id,
        "country": "US",
        "risk_tolerance": "medium",
        "cashflow": {"monthly_income": 5000, "monthly_expenses": 3800},
        "assets": [],
        "liabilities": [],
        "goals": [],
        "preferences": {},
    }


def test_negative_missing_profile_query_returns_404(test_client):
    res = test_client.post("/query", json={"user_id": "missing-user", "query": "Any advice?"})
    assert res.status_code == 404
    assert res.json()["detail"] == "Profile not found."


def test_negative_missing_profile_recommendations_returns_404(test_client):
    res = test_client.post("/recommendations", json={"user_id": "missing-user", "focus": "overview"})
    assert res.status_code == 404
    assert res.json()["detail"] == "Profile not found."


def test_negative_profile_user_id_mismatch_returns_400(test_client):
    payload = {"profile": _create_profile("body-user")}
    res = test_client.put("/profiles/path-user", json=payload)
    assert res.status_code == 400
    assert res.json()["detail"] == "Path user_id must match profile.user_id."


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"title": "X"},
        {"content": "Y"},
        {"title": "", "content": "Y"},
        {"title": "X", "content": ""},
    ],
)
def test_negative_ingest_invalid_payload_returns_422(test_client, payload):
    res = test_client.post("/context/ingest", json=payload)
    assert res.status_code == 422


def test_negative_profiles_get_missing_returns_404(test_client):
    res = test_client.get("/profiles/does-not-exist")
    assert res.status_code == 404
    assert res.json()["detail"] == "Profile not found."

