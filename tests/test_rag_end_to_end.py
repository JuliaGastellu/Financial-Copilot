from __future__ import annotations

from app.rag.ingestion import ingest_public_document
from tests.engine_helpers import recommend

MACRO = (
    "Central banks signaled that policy rates may stay elevated for longer.\n"
    "Inflation has moderated but remains above target in some regions.\n"
    "When interest rates are high, cash equivalents such as short-term instruments may offer attractive yields.\n"
)


def test_public_corpus_ingest_and_query_offline(client, auth):
    container = client.app.state.container
    result = ingest_public_document(
        settings=container.settings, corpus=container.corpus, vector=container.vector, title="Macro update", source="https://example.org/macro", content=MACRO
    )
    assert result.doc_id and result.chunks_indexed >= 1
    again = ingest_public_document(
        settings=container.settings, corpus=container.corpus, vector=container.vector, title="Macro update", source="https://example.org/macro", content=MACRO
    )
    assert again.doc_id == result.doc_id and again.chunks_indexed == 0

    res = client.post("/v1/knowledge/query", json={"query": "How do high interest rates affect my plan?"}, headers=auth("u2"))
    assert res.status_code == 200
    body = res.json()
    assert body["mode"] == "offline"
    assert "interest" in body["answer"].lower()
    assert len(body["citations"]) >= 1


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
