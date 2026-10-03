"""Identidad local para desarrollo (no usar en producción).

Uso:
    python scripts/dev_identity.py init             # crea data/dev_identity/{key.pem,jwks.json}
    python scripts/dev_identity.py token --subject demo-person

Configuro OIDC_ISSUER=http://127.0.0.1/dev-issuer, OIDC_AUDIENCE=financial-copilot-local y
OIDC_JWKS_URL=file:data/dev_identity/jwks.json en el .env local.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.auth.dev_identity import LocalSigningKey, issue_token, jwks

DIR = ROOT / "data" / "dev_identity"
ISSUER = "http://127.0.0.1/dev-issuer"
AUDIENCE = "financial-copilot-local"


def main() -> None:
    parser = argparse.ArgumentParser(description="Identidad local de desarrollo.")
    parser.add_argument("action", choices=["init", "token"])
    parser.add_argument("--subject", default="demo-person")
    parser.add_argument("--minutes", type=int, default=15)
    args = parser.parse_args()
    if args.action == "init":
        DIR.mkdir(parents=True, exist_ok=True)
        key = LocalSigningKey()
        (DIR / "key.pem").write_bytes(key.private_pem())
        (DIR / "kid.txt").write_text(key.kid, encoding="utf-8")
        (DIR / "jwks.json").write_text(json.dumps(jwks(key)), encoding="utf-8")
        print(f"jwks={DIR / 'jwks.json'}")
        return
    key = LocalSigningKey.from_pem((DIR / "kid.txt").read_text(encoding="utf-8").strip(), (DIR / "key.pem").read_bytes())
    print(issue_token(key, issuer=ISSUER, audience=AUDIENCE, subject=args.subject, lifetime_seconds=args.minutes * 60))


if __name__ == "__main__":
    main()
