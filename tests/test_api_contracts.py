from __future__ import annotations

from app.rag.ingestion import ingest_public_document
from tests.v1_payloads import goal_v1, profile_v1


def _ingest(client, content: str) -> None:
    container = client.app.state.container
    ingest_public_document(
        settings=container.settings, corpus=container.corpus, vector=container.vector, title="Macro", source="contract-test", content=content
    )


def test_contract_profile_get_response_shape(client, auth):
    assert client.put("/v1/profile", json=profile_v1(), headers=auth("c1")).status_code == 200
    body = client.get("/v1/profile", headers=auth("c1")).json()
    assert set(body.keys()) == {"profile", "updated_at"}
    assert body["profile"]["currency"] == "USD"


def test_contract_knowledge_query_shape_with_docs(client, auth):
    _ingest(client, "Policy rates remain elevated. Inflation eased compared to last year.")
    res = client.post("/v1/knowledge/query", json={"query": "How do rates affect my decisions?"}, headers=auth("c2"))
    assert res.status_code == 200
    body = res.json()
    assert set(body.keys()) == {"answer", "citations", "corpus", "mode"}
    assert body["answer"].strip()
    assert body["corpus"] == "public"
    assert all("doc_id" in c for c in body["citations"])
    # Retiré `confidence`: era una constante o un valor del modelo sin calibrar.
    assert "confidence" not in body


def test_contract_knowledge_query_shape_without_docs(client, auth):
    res = client.post("/v1/knowledge/query", json={"query": "What should I do this month?"}, headers=auth("c3"))
    assert res.status_code == 200
    body = res.json()
    assert body["answer"].strip()
    assert body["citations"] == []


def test_contract_plan_record_shape(client, auth):
    h = auth("c4")
    client.put("/v1/profile", json=profile_v1(), headers=h)
    client.post("/v1/goals", json=goal_v1(), headers=h)
    res = client.post("/v1/plans", json={"as_of": "2026-10-03"}, headers=h)
    assert res.status_code == 201
    body = res.json()
    assert set(body.keys()) == {"id", "as_of", "policy_version", "created_at", "plan"}
    assert body["as_of"] == "2026-10-03"
    assert {"budgets", "goals", "constraints", "assumptions", "missing_data", "scenarios"} <= set(body["plan"].keys())
