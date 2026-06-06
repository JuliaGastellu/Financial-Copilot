from __future__ import annotations


def test_profile_upsert_and_get(test_client):
    profile = {
        "user_id": "u1",
        "country": "US",
        "risk_tolerance": "medium",
        "cashflow": {"monthly_income": 5000, "monthly_expenses": 3800},
        "assets": [{"name": "Checking", "category": "cash", "value": 4000, "liquidity": "high"}],
        "liabilities": [{"name": "Card", "balance": 1200, "apr": 22.0, "minimum_payment": 60}],
        "goals": [{"name": "Emergency fund", "target_amount": 12000, "horizon_months": 12, "priority": "high"}],
        "preferences": {"constraints": ["no leverage"]},
    }

    res = test_client.put("/profiles/u1", json={"profile": profile})
    assert res.status_code == 200

    res = test_client.get("/profiles/u1")
    assert res.status_code == 200
    body = res.json()
    assert body["profile"]["user_id"] == "u1"
    assert body["profile"]["cashflow"]["monthly_income"] == 5000

