from __future__ import annotations


def test_health(test_client):
    res = test_client.get("/health")
    assert res.status_code == 200
    assert res.json() == {"status": "ok"}

