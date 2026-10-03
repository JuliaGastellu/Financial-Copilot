"""Identidad local para desarrollo y pruebas. Producción rechaza JWKS que no usen https.

Genero un par de claves RSA, publico el JWKS y emito tokens con los mismos claims que
un proveedor OIDC. Nunca uso estas claves fuera de la máquina local.
"""
from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from jwt.algorithms import RSAAlgorithm


@dataclass
class LocalSigningKey:
    kid: str = field(default_factory=lambda: uuid.uuid4().hex[:16])
    private_key: Any = field(default_factory=lambda: rsa.generate_private_key(public_exponent=65537, key_size=2048))

    def public_jwk(self) -> dict[str, Any]:
        jwk = json.loads(RSAAlgorithm.to_jwk(self.private_key.public_key()))
        jwk.update({"kid": self.kid, "use": "sig", "alg": "RS256"})
        return jwk

    def private_pem(self) -> bytes:
        return self.private_key.private_bytes(
            serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
        )

    @classmethod
    def from_pem(cls, kid: str, pem: bytes) -> LocalSigningKey:
        return cls(kid=kid, private_key=serialization.load_pem_private_key(pem, password=None))


def jwks(*keys: LocalSigningKey) -> dict[str, Any]:
    return {"keys": [k.public_jwk() for k in keys]}


def issue_token(
    key: LocalSigningKey,
    *,
    issuer: str,
    audience: str,
    subject: str,
    lifetime_seconds: int = 900,
    now: float | None = None,
    extra: dict[str, Any] | None = None,
    headers: dict[str, Any] | None = None,
) -> str:
    issued = int(now if now is not None else time.time())
    claims: dict[str, Any] = {"iss": issuer, "aud": audience, "sub": subject, "iat": issued, "exp": issued + lifetime_seconds}
    claims.update(extra or {})
    return jwt.encode(claims, key.private_key, algorithm="RS256", headers={"kid": key.kid, **(headers or {})})
