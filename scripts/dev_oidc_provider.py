"""Proveedor OIDC local para desarrollo y QA. No es apto para producción.

Implementa el subconjunto que usa la aplicación web: descubrimiento, autorización con PKCE
(S256), canje de código, JWKS y cierre de sesión. Escucha solo en 127.0.0.1, genera claves
nuevas en memoria en cada arranque y acepta únicamente redirecciones a 127.0.0.1 o localhost.

Uso:
    python scripts/dev_oidc_provider.py --port 8765 --audience financial-copilot-local

La API debe confiar en este emisor solo fuera de producción:
    OIDC_ISSUER=http://127.0.0.1:8765  OIDC_JWKS_URL=http://127.0.0.1:8765/jwks
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import html
import json
import secrets
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.auth.dev_identity import LocalSigningKey, jwks  # noqa: E402

import jwt  # noqa: E402

ALLOWED_REDIRECT_HOSTS = {"127.0.0.1", "localhost"}


class Provider:
    def __init__(self, issuer: str, audience: str, client_id: str, default_lifetime: int) -> None:
        self.issuer = issuer
        self.audience = audience
        self.client_id = client_id
        self.default_lifetime = default_lifetime
        self.key = LocalSigningKey()
        self.codes: dict[str, dict] = {}

    def discovery(self) -> dict:
        return {
            "issuer": self.issuer,
            "authorization_endpoint": f"{self.issuer}/authorize",
            "token_endpoint": f"{self.issuer}/token",
            "jwks_uri": f"{self.issuer}/jwks",
            "end_session_endpoint": f"{self.issuer}/logout",
            "response_types_supported": ["code"],
            "grant_types_supported": ["authorization_code"],
            "code_challenge_methods_supported": ["S256"],
            "subject_types_supported": ["public"],
            "id_token_signing_alg_values_supported": ["RS256"],
            "token_endpoint_auth_methods_supported": ["none"],
            "scopes_supported": ["openid"],
        }

    def sign(self, claims: dict) -> str:
        return jwt.encode(claims, self.key.private_key, algorithm="RS256", headers={"kid": self.key.kid})


def _redirect_allowed(uri: str) -> bool:
    parsed = urlparse(uri)
    return parsed.scheme == "http" and parsed.hostname in ALLOWED_REDIRECT_HOSTS


def make_handler(provider: Provider):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt: str, *args) -> None:  # silencio el registro por solicitud
            return

        def _json(self, status: int, body: dict) -> None:
            data = json.dumps(body).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _redirect(self, location: str) -> None:
            self.send_response(302)
            self.send_header("Location", location)
            self.end_headers()

        def do_OPTIONS(self) -> None:
            self.send_response(204)
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.send_header("Access-Control-Allow-Methods", "GET, POST")
            self.end_headers()

        def do_GET(self) -> None:
            url = urlparse(self.path)
            query = {k: v[0] for k, v in parse_qs(url.query).items()}
            if url.path == "/.well-known/openid-configuration":
                return self._json(200, provider.discovery())
            if url.path == "/jwks":
                return self._json(200, jwks(provider.key))
            if url.path == "/logout":
                target = query.get("post_logout_redirect_uri")
                if target and _redirect_allowed(target):
                    return self._redirect(target + ("?" + urlencode({"state": query["state"]}) if query.get("state") else ""))
                return self._json(200, {"signed_out": True})
            if url.path == "/authorize":
                return self._authorize_form(query)
            self._json(404, {"error": "not_found"})

        def _authorize_form(self, query: dict) -> None:
            required = ("client_id", "redirect_uri", "code_challenge", "state")
            if any(not query.get(k) for k in required) or query.get("code_challenge_method") != "S256":
                return self._json(400, {"error": "invalid_request"})
            if query["client_id"] != provider.client_id or not _redirect_allowed(query["redirect_uri"]):
                return self._json(400, {"error": "unauthorized_client"})
            hidden = "".join(
                f'<input type="hidden" name="{html.escape(k)}" value="{html.escape(v)}">' for k, v in query.items()
            )
            page = f"""<!doctype html><html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>Identidad local de desarrollo</title>
<style>body{{font-family:system-ui,sans-serif;max-width:28rem;margin:2rem auto;padding:0 1rem;color:#1a1a1a}}
label{{display:block;margin-top:1rem;font-weight:600}}input{{font-size:1rem;padding:.5rem;width:100%;box-sizing:border-box}}
button{{margin-top:1.5rem;font-size:1rem;padding:.6rem 1rem;background:#1f4fd1;color:#fff;border:0;border-radius:.4rem}}
p.note{{background:#fff4d6;padding:.75rem;border-radius:.4rem}}</style></head><body>
<h1>Identidad local de desarrollo</h1>
<p class="note">Este formulario solo existe en desarrollo. No uses datos reales.</p>
<form method="post" action="/authorize">{hidden}
<label for="subject">Identificador de prueba</label>
<input id="subject" name="subject" required autocomplete="off" value="persona-demo">
<label for="lifetime">Duración de la sesión en segundos</label>
<input id="lifetime" name="lifetime" type="number" min="1" max="86400" value="{provider.default_lifetime}">
<button type="submit">Continuar</button></form></body></html>"""
            data = page.encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _form(self) -> dict:
            length = int(self.headers.get("Content-Length") or 0)
            return {k: v[0] for k, v in parse_qs(self.rfile.read(length).decode()).items()}

        def do_POST(self) -> None:
            url = urlparse(self.path)
            form = self._form()
            if url.path == "/authorize":
                if not _redirect_allowed(form.get("redirect_uri", "")) or form.get("client_id") != provider.client_id:
                    return self._json(400, {"error": "invalid_request"})
                subject = (form.get("subject") or "").strip()[:200]
                if not subject:
                    return self._json(400, {"error": "invalid_request"})
                code = secrets.token_urlsafe(24)
                provider.codes[code] = {
                    "subject": subject,
                    "client_id": form["client_id"],
                    "redirect_uri": form["redirect_uri"],
                    "challenge": form["code_challenge"],
                    "nonce": form.get("nonce"),
                    "lifetime": max(1, min(86400, int(form.get("lifetime") or provider.default_lifetime))),
                    "expires": time.time() + 120,
                }
                return self._redirect(form["redirect_uri"] + "?" + urlencode({"code": code, "state": form["state"]}))
            if url.path == "/token":
                grant = provider.codes.pop(form.get("code", ""), None)
                if grant is None or grant["expires"] < time.time() or form.get("grant_type") != "authorization_code":
                    return self._json(400, {"error": "invalid_grant"})
                if form.get("redirect_uri") != grant["redirect_uri"] or form.get("client_id") != grant["client_id"]:
                    return self._json(400, {"error": "invalid_grant"})
                digest = hashlib.sha256((form.get("code_verifier") or "").encode()).digest()
                if base64.urlsafe_b64encode(digest).decode().rstrip("=") != grant["challenge"]:
                    return self._json(400, {"error": "invalid_grant"})
                now = int(time.time())
                lifetime = grant["lifetime"]
                access = provider.sign(
                    {"iss": provider.issuer, "aud": provider.audience, "sub": grant["subject"], "iat": now, "exp": now + lifetime}
                )
                id_claims = {"iss": provider.issuer, "aud": provider.client_id, "sub": grant["subject"], "iat": now, "exp": now + lifetime}
                if grant["nonce"]:
                    id_claims["nonce"] = grant["nonce"]
                return self._json(
                    200,
                    {
                        "access_token": access,
                        "id_token": provider.sign(id_claims),
                        "token_type": "Bearer",
                        "expires_in": lifetime,
                        "scope": "openid",
                    },
                )
            self._json(404, {"error": "not_found"})

    return Handler


def main() -> None:
    parser = argparse.ArgumentParser(description="Proveedor OIDC local de desarrollo.")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--audience", default="financial-copilot-local")
    parser.add_argument("--client-id", default="financial-copilot-web")
    parser.add_argument("--lifetime", type=int, default=900, help="Duración por defecto de los tokens, en segundos.")
    args = parser.parse_args()
    issuer = f"http://127.0.0.1:{args.port}"
    provider = Provider(issuer, args.audience, args.client_id, args.lifetime)
    server = ThreadingHTTPServer(("127.0.0.1", args.port), make_handler(provider))
    print(f"issuer={issuer}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
