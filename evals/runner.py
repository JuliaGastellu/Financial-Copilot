"""Evaluación de explicación de planes y respuestas educativas sobre 60 casos ficticios.

Modo `scripted`: proveedor simulado con guiones adversariales; corre en CI y es determinístico.
Mide si el sistema detecta errores y nunca entrega contradicciones, no la calidad de un modelo.
Modo `real`: usa el proveedor configurado (requiere clave); es optativo y tiene costo.
"""
from __future__ import annotations

import json
import statistics
import tempfile
import time
import uuid
from dataclasses import replace
from datetime import date
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from app.auth.dev_identity import LocalSigningKey, issue_token, jwks
from app.core.config import Settings
from app.explain.facts import build_facts
from app.explain.provider import build_provider
from app.explain.validation import ExplanationOutput, ExplanationRejected, validate_output
from app.main import create_app
from app.rag.corpus_files import load_curated_dir
from app.rag.ingestion import ingest_public_document
from app.rag.safety import injection_reason
from app.schemas.plans_v1 import PlanResultV1
from evals.fake_provider import ScriptedProvider

ROOT = Path(__file__).resolve().parent
CASES = ROOT / "cases_v1.json"
CORPUS = ROOT / "corpus_v1"
ISSUER, AUDIENCE = "https://eval.invalid/", "eval"
EVAL_TODAY = date(2026, 10, 3)


class _Jwks:
    def __init__(self, key: LocalSigningKey) -> None:
        self.key = key

    def fetch(self) -> dict:
        return jwks(self.key)


def _profile_payload(p: dict) -> tuple[dict, list[dict]]:
    cur = p["currency"]
    money = lambda a: {"amount": a, "currency": cur}  # noqa: E731
    profile = {
        "currency": cur,
        "cashflows": [{"currency": cur, "monthly_income": p["income"], "monthly_expenses": p["expenses"], "minimum_payments_included_in_expenses": True}],
        "assets": [{"name": "Cuenta", "category": "cash", "liquidity": "high", "value": money(p["cash"])}],
        "liabilities": [],
        "commitments": [],
    }
    if p.get("debt"):
        name, balance, apr, minimum = p["debt"]
        profile["liabilities"] = [{"name": name, "balance": money(balance), "apr_percent": apr, "minimum_payment": money(minimum)}]
    goals = [
        {"name": name, "target": money(amount), "priority": prio, "horizon_months": months}
        for name, amount, months, prio in p["goals"]
    ]
    return profile, goals


def _unrender(output: ExplanationOutput, labels: dict[str, str]) -> dict:
    """Vuelvo a las etiquetas para revalidar el texto entregado contra los hechos."""
    data = output.model_dump()
    for point in [data["summary"], *data["points"]]:
        for label, name in labels.items():
            point["text"] = point["text"].replace(f"«{name}»", label)
    return data


def _percentile(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(round(q * (len(ordered) - 1))))]


def run(mode: str = "scripted", price_in_per_1k: float = 0.0, price_out_per_1k: float = 0.0) -> dict[str, Any]:
    spec = json.loads(CASES.read_text(encoding="utf-8"))
    profiles = {p["label"]: p for p in spec["profiles"]}
    key = LocalSigningKey()
    results: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        settings = Settings(
            _env_file=None,
            environment="test",
            data_dir=Path(tmp),
            offline_mode=mode != "real",
            rate_limit_enabled=False,
            oidc_issuer=ISSUER,
            oidc_audience=AUDIENCE,
            oidc_jwks_url="https://eval.invalid/jwks",
            allowed_origins=["http://127.0.0.1:4173"],
            explanation_daily_quota=1000,
            explanation_daily_token_budget=10_000_000,
        )
        with TestClient(create_app(settings_override=settings, jwks_source=_Jwks(key))) as client:
            container = client.app.state.container
            for doc in load_curated_dir(CORPUS):
                ingest_public_document(
                    settings=settings, corpus=container.corpus, vector=container.vector, title=doc.title, content=doc.content,
                    provenance=doc.provenance, registry=container.registry,
                )
            titles = {d.slug: d.title for d in load_curated_dir(CORPUS)}
            real_provider = build_provider(Settings()) if mode == "real" else None

            for case in spec["cases"]:
                subject = f"{case['id']}-{uuid.uuid4().hex[:6]}"
                headers = {"Authorization": f"Bearer {issue_token(key, issuer=ISSUER, audience=AUDIENCE, subject=subject)}"}
                if case["kind"] == "educational":
                    started = time.perf_counter()
                    answer = container.knowledge.answer(case["query"], None, today=EVAL_TODAY)
                    latency = (time.perf_counter() - started) * 1000
                    exp = case["expected"]
                    cited_titles = {c["title"] for c in answer["citations"]}
                    usable = container.corpus.usable_by_ids([c["citations"][0]["chunk_id"] for c in answer["claims"]], EVAL_TODAY)
                    supported = sum(
                        1
                        for c in answer["claims"]
                        if c["citations"] and (row := usable.get(c["citations"][0]["chunk_id"])) is not None and c["text"] in row["content"]
                    )
                    injected = any(injection_reason(c["text"]) for c in answer["claims"])
                    ok = answer["status"] == exp["status"] and answer["abstention_reason"] == exp["abstention_reason"]
                    if exp.get("must_cite"):
                        ok = ok and titles[exp["must_cite"]] in cited_titles
                    results.append(
                        {
                            "id": case["id"], "kind": "educational", "ok": ok and not injected, "status": answer["status"],
                            "abstention_reason": answer["abstention_reason"], "expected": exp, "claims": len(answer["claims"]),
                            "supported_claims": supported, "injected": injected, "latency_ms": round(latency, 2),
                            "designed_abstention": exp["status"] == "abstained",
                        }
                    )
                    continue

                profile, goals = _profile_payload(profiles[case["profile"]])
                client.put("/v1/profile", json=profile, headers=headers)
                for g in goals:
                    client.post("/v1/goals", json=g, headers=headers)
                plan = client.post("/v1/plans", json={"as_of": EVAL_TODAY.isoformat()}, headers={**headers, "Idempotency-Key": f"eval-{uuid.uuid4()}"}).json()
                provider = real_provider or ScriptedProvider(script=case["provider_script"])
                client.app.state.container = replace(container, explanations=replace(container.explanations, provider=provider))
                started = time.perf_counter()
                res = client.post(f"/v1/plans/{plan['id']}/explanation", headers=headers)
                latency = (time.perf_counter() - started) * 1000
                client.app.state.container = container
                body = res.json()
                result = PlanResultV1.model_validate(plan["result"])
                pf = build_facts(result)
                delivered = ExplanationOutput.model_validate({"summary": body["summary"], "points": body["points"]})
                try:
                    validate_output(pf, _unrender(delivered, pf.labels))
                    contradiction = None
                except ExplanationRejected as exc:
                    contradiction = exc.code
                with container.engine.connect() as conn:
                    from sqlalchemy import select

                    from app.db.schema import plan_explanations

                    row = conn.execute(select(plan_explanations.c.input_tokens, plan_explanations.c.output_tokens).where(plan_explanations.c.plan_id == plan["id"])).first()
                tokens_in, tokens_out = (row.input_tokens, row.output_tokens) if row else (0, 0)
                expected_source = case["expected"]["source"]
                results.append(
                    {
                        "id": case["id"], "kind": "explanation", "critical": case["critical"], "script": case.get("provider_script"),
                        "source": body["source"], "fallback_reason": body["fallback_reason"], "expected_source": expected_source,
                        "ok": contradiction is None and (mode == "real" or body["source"] == expected_source),
                        "delivered_contradiction": contradiction, "points": 1 + len(body["points"]),
                        "supported_points": 0 if contradiction else 1 + len(body["points"]), "latency_ms": round(latency, 2),
                        "input_tokens": tokens_in, "output_tokens": tokens_out,
                    }
                )

    edu = [r for r in results if r["kind"] == "educational"]
    exp = [r for r in results if r["kind"] == "explanation"]
    designed = [r for r in edu if r["designed_abstention"]]
    answerable = [r for r in edu if not r["designed_abstention"]]
    claims_total = sum(r["claims"] for r in edu) + sum(r["points"] for r in exp)
    claims_supported = sum(r["supported_claims"] for r in edu) + sum(r["supported_points"] for r in exp)
    tokens_in = sum(r["input_tokens"] for r in exp)
    tokens_out = sum(r["output_tokens"] for r in exp)
    metrics = {
        "cases": len(results),
        "critical_cases": sum(1 for r in exp if r["critical"]),
        "critical_contradictions_delivered": sum(1 for r in exp if r["critical"] and r["delivered_contradiction"]),
        "contradictions_delivered": sum(1 for r in exp if r["delivered_contradiction"]),
        "plan_fidelity": round(sum(1 for r in exp if not r["delivered_contradiction"]) / max(1, len(exp)), 4),
        "provider_outputs_accepted": sum(1 for r in exp if r["source"] == "provider"),
        "expected_source_matches": sum(1 for r in exp if r["source"] == r["expected_source"]),
        "claims_total": claims_total,
        "claims_supported": claims_supported,
        "claim_support_rate": round(claims_supported / max(1, claims_total), 4),
        "designed_abstentions": len(designed),
        "designed_abstentions_correct": sum(1 for r in designed if r["status"] == "abstained" and r["ok"]),
        "abstention_rate_designed": round(sum(1 for r in designed if r["status"] == "abstained") / max(1, len(designed)), 4),
        "answerable_cases": len(answerable),
        "answerable_answered_with_expected_citation": sum(1 for r in answerable if r["ok"]),
        "injected_claims": sum(1 for r in edu if r["injected"]),
        "latency_ms": {
            "educational_p50": round(statistics.median([r["latency_ms"] for r in edu]), 2),
            "educational_p95": round(_percentile([r["latency_ms"] for r in edu], 0.95), 2),
            "explanation_p50": round(statistics.median([r["latency_ms"] for r in exp]), 2),
            "explanation_p95": round(_percentile([r["latency_ms"] for r in exp], 0.95), 2),
        },
        "tokens": {"input": tokens_in, "output": tokens_out},
        "estimated_cost": round(tokens_in / 1000 * price_in_per_1k + tokens_out / 1000 * price_out_per_1k, 6),
    }
    return {"version": spec["version"], "mode": mode, "metrics": metrics, "failures": [r for r in results if not r["ok"]], "results": results}


def run_holdout() -> dict[str, Any]:
    """Corro las preguntas reservadas una vez, sin usarlas para calibrar."""
    spec = json.loads((ROOT / "holdout_v1.json").read_text(encoding="utf-8"))
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        settings = Settings(_env_file=None, environment="test", data_dir=Path(tmp), offline_mode=True, rate_limit_enabled=False,
                            oidc_issuer=ISSUER, oidc_audience=AUDIENCE, oidc_jwks_url="https://eval.invalid/jwks")
        with TestClient(create_app(settings_override=settings, jwks_source=_Jwks(LocalSigningKey()))) as client:
            c = client.app.state.container
            docs = load_curated_dir(CORPUS)
            for doc in docs:
                ingest_public_document(settings=settings, corpus=c.corpus, vector=c.vector, title=doc.title, content=doc.content,
                                       provenance=doc.provenance, registry=c.registry)
            titles = {d.slug: d.title for d in docs}
            rows = []
            for case in spec["cases"]:
                answer = c.knowledge.answer(case["query"], None, today=EVAL_TODAY)
                exp = case["expected"]
                ok = answer["status"] == exp["status"] and (not exp.get("must_cite") or titles[exp["must_cite"]] in {x["title"] for x in answer["citations"]})
                rows.append({"id": case["id"], "ok": ok, "status": answer["status"], "expected": exp})
    answerable = [r for r in rows if r["expected"]["status"] == "answered"]
    abstain = [r for r in rows if r["expected"]["status"] == "abstained"]
    return {
        "version": spec["version"],
        "answerable_correct": f"{sum(r['ok'] for r in answerable)}/{len(answerable)}",
        "abstention_correct": f"{sum(r['ok'] for r in abstain)}/{len(abstain)}",
        "failures": [r for r in rows if not r["ok"]],
    }
