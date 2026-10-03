"""Ejecuto la evaluación y guardo el informe.

Uso:
    python -m evals.run_eval                       # proveedor simulado, sin costo
    python -m evals.run_eval --mode real \
        --price-in 0.00015 --price-out 0.0006      # proveedor configurado en .env (optativo)

El modo real necesita EXPLANATION_PROVIDER=openai_compatible y OPENAI_API_KEY. Los precios
por 1000 tokens se pasan a mano: no los invento ni los consulto.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from evals.runner import run  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluación de explicación y respuestas educativas.")
    parser.add_argument("--mode", choices=["scripted", "real"], default="scripted")
    parser.add_argument("--price-in", type=float, default=0.0, help="Precio por 1000 tokens de entrada.")
    parser.add_argument("--price-out", type=float, default=0.0, help="Precio por 1000 tokens de salida.")
    parser.add_argument("--out", type=Path, default=Path("evals/reports/latest.json"))
    args = parser.parse_args()
    report = run(args.mode, args.price_in, args.price_out)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(json.dumps(report["metrics"], ensure_ascii=False, indent=2))
    for failure in report["failures"]:
        print("FAIL", failure["id"], {k: failure.get(k) for k in ("status", "abstention_reason", "source", "fallback_reason", "delivered_contradiction")})


if __name__ == "__main__":
    main()
