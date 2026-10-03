"""Genero los datos de la demo web con la API real, sobre una base temporal y datos ficticios.

La demo no calcula nada en el navegador: muestra respuestas que produjo este backend.
Uso:
    python scripts/build_web_demo.py   # escribe web/src/demo/demo-data.json
"""
from __future__ import annotations

import json
import sys
import tempfile
import uuid
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient  # noqa: E402

from app.auth.dev_identity import LocalSigningKey, issue_token, jwks  # noqa: E402
from app.core.config import Settings  # noqa: E402
from app.main import create_app  # noqa: E402

ISSUER = "https://demo.invalid/"
AUDIENCE = "demo"
AS_OF = "2026-10-01"
PERIOD = "2026-10"


class _Jwks:
    def __init__(self, key: LocalSigningKey) -> None:
        self.key = key

    def fetch(self) -> dict:
        return jwks(self.key)


def _ok(res, status: int = 200) -> dict:
    if res.status_code != status:
        raise SystemExit(f"Demo generation failed: {res.status_code} {res.text}")
    return res.json()


def build() -> dict:
    key = LocalSigningKey()
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        settings = Settings(
            _env_file=None,
            environment="test",
            data_dir=Path(tmp),
            offline_mode=True,
            rate_limit_enabled=False,
            oidc_issuer=ISSUER,
            oidc_audience=AUDIENCE,
            oidc_jwks_url="https://demo.invalid/jwks",
            allowed_origins=["http://127.0.0.1:4173"],
        )
        headers = {"Authorization": f"Bearer {issue_token(key, issuer=ISSUER, audience=AUDIENCE, subject='demo')}"}

        def idem() -> dict:
            return {**headers, "Idempotency-Key": f"demo-{uuid.uuid4()}"}

        with TestClient(create_app(settings_override=settings, jwks_source=_Jwks(key))) as client:
            profile = {
                "currency": "ARS",
                "cashflows": [{"currency": "ARS", "monthly_income": "1800000", "monthly_expenses": "1250000", "minimum_payments_included_in_expenses": True}],
                "assets": [{"name": "Cuenta", "category": "cash", "liquidity": "high", "value": {"amount": "4200000", "currency": "ARS"}}],
                "liabilities": [],
                "commitments": [],
                "emergency_reserve_months": "3",
                "provenance": {"monthly_income": "estimated", "monthly_expenses": "reported", "balances": "reported", "reserve_months": "reported"},
            }
            _ok(client.put("/v1/profile", json=profile, headers=headers))
            goals = [
                {"name": "Fondo para mudanza", "target": {"amount": "1500000", "currency": "ARS"}, "priority": "high", "horizon_months": 10},
                {"name": "Curso de idioma", "target": {"amount": "600000", "currency": "ARS"}, "priority": "medium", "horizon_months": 6},
            ]
            created = [_ok(client.post("/v1/goals", json=g, headers=headers), 201) for g in goals]
            plan = _ok(client.post("/v1/plans", json={"as_of": AS_OF}, headers=idem()), 201)
            scenario = _ok(
                client.post(
                    "/v1/scenarios",
                    json={"base_plan_id": plan["id"], "name": "Ingreso 20% menor", "income_change": "-0.20"},
                    headers=idem(),
                ),
                201,
            )
            first_goal = created[0]
            planned = next(g for g in plan["result"]["goals"] if g["goal_id"] == first_goal["id"])["monthly_allocation"]
            _ok(
                client.post(
                    "/v1/progress",
                    json={"goal_id": first_goal["id"], "period": PERIOD, "amount": planned, "source": "monthly_surplus"},
                    headers=idem(),
                ),
                201,
            )
            review = _ok(client.get(f"/v1/reviews/{PERIOD}", headers=headers))
            profile_out = _ok(client.get("/v1/profile", headers=headers))
            goals_out = _ok(client.get("/v1/goals", headers=headers))
            current = _ok(client.get("/v1/plans/current", headers=headers))
    return {
        "generated_on": date.today().isoformat(),
        "profile": profile_out,
        "goals": goals_out,
        "current": current,
        "scenario": scenario,
        "review": review,
    }


def main() -> None:
    out = ROOT / "web" / "src" / "demo" / "demo-data.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(build(), ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"wrote {out.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
