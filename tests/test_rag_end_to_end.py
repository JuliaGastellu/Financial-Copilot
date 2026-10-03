from __future__ import annotations

from app.rag.ingestion import ingest_public_document
from tests.engine_helpers import recommend
from tests.v1_payloads import provenance

MACRO = (
    "Central banks signaled that policy rates may stay elevated for longer.\n"
    "Inflation has moderated but remains above target in some regions.\n"
    "When interest rates are high, cash equivalents such as short-term instruments may offer attractive yields.\n"
)


def test_public_corpus_ingest_and_query_offline(client, auth):
    container = client.app.state.container
    result = ingest_public_document(
        settings=container.settings, corpus=container.corpus, vector=container.vector, title="Macro update", content=MACRO, provenance=provenance(), registry=container.registry
    )
    assert result.doc_id and result.chunks_indexed >= 1
    again = ingest_public_document(
        settings=container.settings, corpus=container.corpus, vector=container.vector, title="Macro update", content=MACRO, provenance=provenance(), registry=container.registry
    )
    assert again.doc_id == result.doc_id and again.chunks_indexed == 0

    res = client.post("/v1/knowledge/query", json={"query": "When interest rates are high, are cash equivalents attractive?"}, headers=auth("u2"))
    assert res.status_code == 200
    body = res.json()
    assert body["mode"] == "extractive" and body["status"] == "answered"
    assert "interest" in body["answer"].lower()
    assert len(body["citations"]) >= 1
    for claim in body["claims"]:
        assert claim["text"] in MACRO
        assert claim["citations"][0]["publisher"] == "Material ficticio para pruebas"

    absent = client.post("/v1/knowledge/query", json={"query": "How is property tax assessed on farmland?"}, headers=auth("u2")).json()
    assert absent["status"] == "abstained" and absent["claims"] == []


def test_recommendation_engine_offline():
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
    body = recommend(profile)
    assert "metrics" in body
    assert isinstance(body["recommendations"], list)
    assert body["mode"] == "offline"
