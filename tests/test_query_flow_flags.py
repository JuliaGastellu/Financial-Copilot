from __future__ import annotations


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


def test_query_default_includes_recommendations_and_has_fallback_fields(test_client):
    res = test_client.put("/profiles/q1", json={"profile": _create_profile("q1")})
    assert res.status_code == 200

    res = test_client.post("/query", json={"user_id": "q1", "query": "What should I do this month?"})
    assert res.status_code == 200
    body = res.json()

    assert isinstance(body["recommendations"], list)
    assert len(body["recommendations"]) > 0
    assert "fallback_used" in body
    assert "fallback_reason" in body
    assert isinstance(body["fallback_used"], bool)
    assert body["fallback_reason"] is None or isinstance(body["fallback_reason"], str)


def test_query_can_suppress_recommendations(test_client):
    res = test_client.put("/profiles/q2", json={"profile": _create_profile("q2")})
    assert res.status_code == 200

    res = test_client.post(
        "/context/ingest",
        json={
            "title": "Macro",
            "source": "flag-test",
            "content": "Policy rates remain elevated. Inflation eased compared to last year.",
        },
    )
    assert res.status_code == 200

    res = test_client.post(
        "/query",
        json={
            "user_id": "q2",
            "query": "How do rates affect my decisions?",
            "include_recommendations": False,
        },
    )
    assert res.status_code == 200
    body = res.json()

    assert isinstance(body["answer"], str) and body["answer"].strip()
    assert isinstance(body["citations"], list)
    assert isinstance(body["confidence"], (int, float))
    assert isinstance(body["mode"], str)
    assert isinstance(body["fallback_used"], bool)
    assert body["fallback_reason"] is None or isinstance(body["fallback_reason"], str)

    assert body["recommendations"] == []

