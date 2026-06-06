from __future__ import annotations


def _create_profile(user_id: str) -> dict:
    return {
        "user_id": user_id,
        "country": "US",
        "risk_tolerance": "medium",
        "cashflow": {"monthly_income": 5000, "monthly_expenses": 3800},
        "assets": [{"name": "Checking", "category": "cash", "value": 4000, "liquidity": "high"}],
        "liabilities": [{"name": "Card", "balance": 1200, "apr": 22.0, "minimum_payment": 60}],
        "goals": [{"name": "Emergency fund", "target_amount": 12000, "horizon_months": 12, "priority": "high"}],
        "preferences": {"constraints": ["no leverage"]},
    }


def test_contract_profiles_get_response_shape(test_client):
    profile = _create_profile("c1")
    res = test_client.put("/profiles/c1", json={"profile": profile})
    assert res.status_code == 200

    res = test_client.get("/profiles/c1")
    assert res.status_code == 200
    body = res.json()
    assert set(body.keys()) == {"profile"}
    assert isinstance(body["profile"], dict)
    assert body["profile"]["user_id"] == "c1"


def test_contract_query_response_shape_with_docs(test_client):
    profile = _create_profile("c2")
    res = test_client.put("/profiles/c2", json={"profile": profile})
    assert res.status_code == 200

    res = test_client.post(
        "/context/ingest",
        json={
            "title": "Macro",
            "source": "contract-test",
            "content": "Policy rates remain elevated. Inflation eased compared to last year.",
        },
    )
    assert res.status_code == 200

    res = test_client.post("/query", json={"user_id": "c2", "query": "How do rates affect my decisions?"})
    assert res.status_code == 200
    body = res.json()

    assert set(body.keys()) == {
        "answer",
        "recommendations",
        "citations",
        "confidence",
        "mode",
        "fallback_used",
        "fallback_reason",
    }
    assert isinstance(body["answer"], str)
    assert body["answer"].strip()

    assert isinstance(body["recommendations"], list)
    for rec in body["recommendations"]:
        assert isinstance(rec, dict)

    assert isinstance(body["citations"], list)
    for c in body["citations"]:
        assert isinstance(c, dict)
        assert "doc_id" in c

    assert isinstance(body["confidence"], (int, float))
    assert 0.0 <= float(body["confidence"]) <= 1.0

    assert isinstance(body["mode"], str)
    assert body["mode"] in ("offline", "llm")

    assert isinstance(body["fallback_used"], bool)
    assert body["fallback_reason"] is None or isinstance(body["fallback_reason"], str)


def test_contract_query_response_shape_without_docs(test_client):
    profile = _create_profile("c3")
    res = test_client.put("/profiles/c3", json={"profile": profile})
    assert res.status_code == 200

    res = test_client.post("/query", json={"user_id": "c3", "query": "What should I do this month?"})
    assert res.status_code == 200
    body = res.json()

    assert set(body.keys()) == {
        "answer",
        "recommendations",
        "citations",
        "confidence",
        "mode",
        "fallback_used",
        "fallback_reason",
    }
    assert isinstance(body["answer"], str)
    assert body["answer"].strip()
    assert isinstance(body["citations"], list)
    assert isinstance(body["recommendations"], list)
    assert isinstance(body["confidence"], (int, float))
    assert 0.0 <= float(body["confidence"]) <= 1.0
    assert isinstance(body["mode"], str)
    assert body["mode"] in ("offline", "llm")
    assert isinstance(body["fallback_used"], bool)
    assert body["fallback_reason"] is None or isinstance(body["fallback_reason"], str)


def test_contract_recommendations_response_shape(test_client):
    profile = _create_profile("c4")
    res = test_client.put("/profiles/c4", json={"profile": profile})
    assert res.status_code == 200

    res = test_client.post("/recommendations", json={"user_id": "c4", "focus": "overview"})
    assert res.status_code == 200
    body = res.json()

    assert {"metrics", "recommendations", "mode"}.issubset(set(body.keys()))
    assert isinstance(body["metrics"], dict)
    assert isinstance(body["recommendations"], list)
    assert isinstance(body["mode"], str)
    assert body["mode"] in ("offline", "llm")

    for rec in body["recommendations"]:
        assert isinstance(rec, dict)
        assert {"title", "rationale", "actions", "risks", "sources"}.issubset(set(rec.keys()))
        assert isinstance(rec["title"], str) and rec["title"].strip()
        assert isinstance(rec["rationale"], str) and rec["rationale"].strip()
        assert isinstance(rec["actions"], list) and all(isinstance(a, str) and a.strip() for a in rec["actions"])
        assert isinstance(rec["risks"], list) and all(isinstance(r, str) for r in rec["risks"])
        assert isinstance(rec["sources"], list)
        for s in rec["sources"]:
            assert isinstance(s, dict)
            assert "doc_id" in s
