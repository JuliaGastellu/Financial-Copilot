from __future__ import annotations


def test_rag_ingest_and_query_offline(test_client):
    macro = (
        "Central banks signaled that policy rates may stay elevated for longer.\n"
        "Inflation has moderated but remains above target in some regions.\n"
        "When interest rates are high, cash equivalents such as short-term instruments may offer attractive yields.\n"
    )
    res = test_client.post("/context/ingest", json={"title": "Macro update", "source": "internal", "content": macro})
    assert res.status_code == 200
    doc_id = res.json()["doc_id"]
    assert doc_id

    profile = {
        "user_id": "u2",
        "country": "US",
        "risk_tolerance": "low",
        "cashflow": {"monthly_income": 4000, "monthly_expenses": 3300},
        "assets": [{"name": "Checking", "category": "cash", "value": 2500, "liquidity": "high"}],
        "liabilities": [{"name": "Card", "balance": 900, "apr": 18.0, "minimum_payment": 40}],
        "goals": [{"name": "Car down payment", "target_amount": 6000, "horizon_months": 10, "priority": "high"}],
        "preferences": {},
    }
    res = test_client.put("/profiles/u2", json={"profile": profile})
    assert res.status_code == 200

    res = test_client.post("/query", json={"user_id": "u2", "query": "How do high interest rates affect my plan?"})
    assert res.status_code == 200
    body = res.json()
    assert body["mode"] == "offline"
    assert "interest" in body["answer"].lower()
    assert len(body["citations"]) >= 1


def test_recommendations_endpoint(test_client):
    profile = {
        "user_id": "u3",
        "country": "US",
        "risk_tolerance": "medium",
        "cashflow": {"monthly_income": 7000, "monthly_expenses": 5200},
        "assets": [{"name": "Checking", "category": "cash", "value": 12000, "liquidity": "high"}],
        "liabilities": [],
        "goals": [{"name": "Retirement", "target_amount": 1000000, "horizon_months": 240, "priority": "high"}],
        "preferences": {},
    }
    res = test_client.put("/profiles/u3", json={"profile": profile})
    assert res.status_code == 200

    res = test_client.post("/recommendations", json={"user_id": "u3", "focus": "overview"})
    assert res.status_code == 200
    body = res.json()
    assert "metrics" in body
    assert "recommendations" in body
    assert isinstance(body["recommendations"], list)
    assert body["mode"] in ("offline", "llm")

