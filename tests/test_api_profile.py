from __future__ import annotations

from tests.v1_payloads import money, profile_v1


def test_profile_upsert_and_get(client, auth):
    profile = profile_v1(
        liabilities=[{"name": "Card", "balance": money(1200), "apr_percent": "22", "minimum_payment": money(60)}],
    )
    res = client.put("/v1/profile", json=profile, headers=auth("u1"))
    assert res.status_code == 200, res.text

    res = client.get("/v1/profile", headers=auth("u1"))
    assert res.status_code == 200
    body = res.json()
    assert body["profile"]["cashflows"][0]["monthly_income"] == "7000.00"
    assert body["profile"]["liabilities"][0]["minimum_payment"] == {"amount": "60.00", "currency": "USD"}
    assert "user_id" not in body["profile"]
