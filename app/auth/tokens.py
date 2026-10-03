"""Verificación de tokens de acceso OIDC (JWT firmados por el proveedor de identidad).

Contrato que acepto:
- Encabezado `Authorization: Bearer <token>`.
- Firma asimétrica (por defecto RS256) con una clave publicada en el JWKS del emisor, elegida por `kid`.
- `iss` igual al emisor configurado y `aud` que incluye la audiencia de esta API.
- `exp`, `iat` y `sub` obligatorios; `nbf` si está presente. Tolero un desfase de reloj acotado.
- Rechazo tokens con `iat` más antiguo que la edad máxima configurada.

El propietario de cada recurso sale solo de (`iss`, `sub`). Nunca de la URL ni del cuerpo.
"""
from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Protocol

import jwt
from jwt import PyJWK

from app.core.config import Settings


class AuthenticationError(Exception):
    """El token falta o no es válido. El mensaje no revela detalles del token."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class Identity:
    issuer: str
    subject: str


class JwksSource(Protocol):
    def fetch(self) -> dict[str, Any]: ...


@dataclass(frozen=True)
class HttpJwksSource:
    url: str
    timeout_seconds: float = 5.0

    def fetch(self) -> dict[str, Any]:
        import httpx

        response = httpx.get(self.url, timeout=self.timeout_seconds, follow_redirects=False)
        response.raise_for_status()
        return response.json()


@dataclass(frozen=True)
class FileJwksSource:
    """Solo para desarrollo local y pruebas: lee un JWKS público desde disco."""

    path: Path

    def fetch(self) -> dict[str, Any]:
        return json.loads(self.path.read_text(encoding="utf-8"))


class JwksCache:
    """Cacheo las claves públicas y recargo ante un `kid` desconocido (rotación),
    con un intervalo mínimo entre recargas para no amplificar tráfico ante tokens falsos."""

    def __init__(
        self,
        source: JwksSource,
        *,
        ttl_seconds: int,
        min_refresh_seconds: int,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._source = source
        self._ttl = ttl_seconds
        self._min_refresh = min_refresh_seconds
        self._clock = clock
        self._keys: dict[str, PyJWK] = {}
        self._loaded_at: float | None = None
        self._lock = threading.Lock()

    def _load(self) -> None:
        data = self._source.fetch()
        keys: dict[str, PyJWK] = {}
        for raw in data.get("keys", []):
            kid = raw.get("kid")
            if not kid or raw.get("use", "sig") != "sig":
                continue
            try:
                keys[kid] = PyJWK.from_dict(raw)
            except Exception:
                continue
        self._keys = keys
        self._loaded_at = self._clock()

    def get(self, kid: str) -> PyJWK:
        with self._lock:
            now = self._clock()
            expired = self._loaded_at is None or now - self._loaded_at >= self._ttl
            can_refresh = self._loaded_at is None or now - self._loaded_at >= self._min_refresh
            if expired or (kid not in self._keys and can_refresh):
                try:
                    self._load()
                except Exception as exc:
                    if not self._keys:
                        raise AuthenticationError("jwks_unavailable") from exc
            key = self._keys.get(kid)
        if key is None:
            raise AuthenticationError("unknown_key")
        return key


class TokenVerifier:
    def __init__(self, settings: Settings, jwks: JwksCache) -> None:
        if not settings.oidc_issuer or not settings.oidc_audience:
            raise ValueError("OIDC issuer and audience are required.")
        self._issuer = settings.oidc_issuer
        self._audience = settings.oidc_audience
        self._algorithms = [a for a in settings.oidc_algorithms if not a.upper().startswith("HS") and a.lower() != "none"]
        self._leeway = settings.oidc_leeway_seconds
        self._max_age = settings.oidc_max_token_age_seconds
        self._jwks = jwks

    def verify(self, token: str) -> Identity:
        try:
            header = jwt.get_unverified_header(token)
        except jwt.PyJWTError as exc:
            raise AuthenticationError("malformed_token") from exc
        alg = header.get("alg")
        if alg not in self._algorithms:
            raise AuthenticationError("algorithm_not_allowed")
        kid = header.get("kid")
        if not isinstance(kid, str) or not kid:
            raise AuthenticationError("missing_kid")
        key = self._jwks.get(kid)
        try:
            claims = jwt.decode(
                token,
                key=key.key,
                algorithms=[alg],
                audience=self._audience,
                issuer=self._issuer,
                leeway=self._leeway,
                options={"require": ["exp", "iat", "iss", "aud", "sub"], "verify_signature": True},
            )
        except jwt.ExpiredSignatureError as exc:
            raise AuthenticationError("token_expired") from exc
        except jwt.InvalidSignatureError as exc:
            raise AuthenticationError("invalid_signature") from exc
        except jwt.InvalidAudienceError as exc:
            raise AuthenticationError("invalid_audience") from exc
        except jwt.InvalidIssuerError as exc:
            raise AuthenticationError("invalid_issuer") from exc
        except jwt.PyJWTError as exc:
            raise AuthenticationError("invalid_token") from exc

        issued_at = claims.get("iat")
        if not isinstance(issued_at, (int, float)) or time.time() - issued_at > self._max_age + self._leeway:
            raise AuthenticationError("token_too_old")
        subject = claims.get("sub")
        if not isinstance(subject, str) or not subject.strip() or len(subject) > 255:
            raise AuthenticationError("invalid_subject")
        return Identity(issuer=self._issuer, subject=subject)


def build_jwks_source(settings: Settings) -> JwksSource:
    url = settings.oidc_jwks_url
    if not url:
        raise ValueError("OIDC_JWKS_URL is required.")
    if url.startswith("https://"):
        return HttpJwksSource(url)
    if settings.environment != "production" and url.startswith("file:"):
        return FileJwksSource(Path(url.removeprefix("file://").removeprefix("file:")))
    if settings.environment != "production" and url.startswith("http://127.0.0.1"):
        return HttpJwksSource(url)
    raise ValueError("OIDC_JWKS_URL must use https (file: and http://127.0.0.1 are allowed only outside production).")
