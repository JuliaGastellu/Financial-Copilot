"""Verificación de tokens con un doble local del proveedor (sin red ni credenciales reales)."""
from __future__ import annotations

import base64
import json
import time

import jwt
import pytest

from app.auth.dev_identity import LocalSigningKey, issue_token
from app.auth.tokens import AuthenticationError, JwksCache, TokenVerifier
from app.core.config import Settings
from tests.conftest import AUDIENCE, ISSUER, MemoryJwks


def _settings(**kw) -> Settings:
    return Settings(_env_file=None, environment="test", oidc_issuer=ISSUER, oidc_audience=AUDIENCE, **kw)


def _verifier(source: MemoryJwks, clock=time.monotonic, **kw) -> TokenVerifier:
    settings = _settings(**kw)
    return TokenVerifier(settings, JwksCache(source, ttl_seconds=600, min_refresh_seconds=30, clock=clock))


def _token(key: LocalSigningKey, **kw) -> str:
    params = {"issuer": ISSUER, "audience": AUDIENCE, "subject": "alice"}
    params.update(kw)
    return issue_token(key, **params)


def test_valid_token_yields_issuer_and_subject() -> None:
    key = LocalSigningKey()
    identity = _verifier(MemoryJwks(key)).verify(_token(key))
    assert (identity.issuer, identity.subject) == (ISSUER, "alice")


@pytest.mark.parametrize(
    "overrides,reason",
    [
        ({"issuer": "https://evil.invalid/"}, "invalid_issuer"),
        ({"audience": "another-api"}, "invalid_audience"),
        ({"now": time.time() - 7200, "lifetime_seconds": 600}, "token_expired"),
        ({"extra": {"nbf": int(time.time()) + 3600}}, "invalid_token"),
    ],
)
def test_claim_violations_are_rejected(overrides, reason) -> None:
    key = LocalSigningKey()
    with pytest.raises(AuthenticationError) as exc:
        _verifier(MemoryJwks(key)).verify(_token(key, **overrides))
    assert exc.value.reason == reason


def test_token_older_than_max_age_is_rejected() -> None:
    key = LocalSigningKey()
    old = _token(key, now=time.time() - 7200, lifetime_seconds=86400)
    with pytest.raises(AuthenticationError) as exc:
        _verifier(MemoryJwks(key), oidc_max_token_age_seconds=3600).verify(old)
    assert exc.value.reason == "token_too_old"


def test_missing_subject_or_expiry_is_rejected() -> None:
    key = LocalSigningKey()
    now = int(time.time())
    no_sub = jwt.encode({"iss": ISSUER, "aud": AUDIENCE, "iat": now, "exp": now + 60}, key.private_key, algorithm="RS256", headers={"kid": key.kid})
    no_exp = jwt.encode({"iss": ISSUER, "aud": AUDIENCE, "iat": now, "sub": "a"}, key.private_key, algorithm="RS256", headers={"kid": key.kid})
    for token in (no_sub, no_exp):
        with pytest.raises(AuthenticationError):
            _verifier(MemoryJwks(key)).verify(token)


def test_signature_from_another_key_with_same_kid_is_rejected() -> None:
    trusted = LocalSigningKey()
    attacker = LocalSigningKey(kid=trusted.kid)
    with pytest.raises(AuthenticationError) as exc:
        _verifier(MemoryJwks(trusted)).verify(_token(attacker))
    assert exc.value.reason == "invalid_signature"


def test_tampered_payload_is_rejected() -> None:
    key = LocalSigningKey()
    header, payload, signature = _token(key).split(".")
    claims = json.loads(base64.urlsafe_b64decode(payload + "=="))
    claims["sub"] = "bob"
    forged = base64.urlsafe_b64encode(json.dumps(claims).encode()).decode().rstrip("=")
    with pytest.raises(AuthenticationError) as exc:
        _verifier(MemoryJwks(key)).verify(f"{header}.{forged}.{signature}")
    assert exc.value.reason == "invalid_signature"


def test_none_and_symmetric_algorithms_are_rejected() -> None:
    key = LocalSigningKey()
    now = int(time.time())
    claims = {"iss": ISSUER, "aud": AUDIENCE, "sub": "a", "iat": now, "exp": now + 60}
    unsigned = jwt.encode(claims, None, algorithm="none", headers={"kid": key.kid})
    # Confusión de algoritmo: firmo HS256 usando la clave pública como secreto (lo armo a mano;
    # PyJWT se niega a hacerlo, que es justamente lo que quiero comprobar del lado del verificador).
    import hashlib
    import hmac

    from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

    public_pem = key.private_key.public_key().public_bytes(Encoding.PEM, PublicFormat.SubjectPublicKeyInfo)

    def b64(data: bytes) -> str:
        return base64.urlsafe_b64encode(data).decode().rstrip("=")

    signing_input = f"{b64(json.dumps({'alg': 'HS256', 'typ': 'JWT', 'kid': key.kid}).encode())}.{b64(json.dumps(claims).encode())}"
    hmac_token = f"{signing_input}.{b64(hmac.new(public_pem, signing_input.encode(), hashlib.sha256).digest())}"
    for token in (unsigned, hmac_token):
        with pytest.raises(AuthenticationError) as exc:
            _verifier(MemoryJwks(key), oidc_algorithms=["RS256", "HS256", "none"]).verify(token)
        assert exc.value.reason == "algorithm_not_allowed"


def test_malformed_and_kidless_tokens_are_rejected() -> None:
    key = LocalSigningKey()
    now = int(time.time())
    no_kid = jwt.encode({"iss": ISSUER, "aud": AUDIENCE, "sub": "a", "iat": now, "exp": now + 60}, key.private_key, algorithm="RS256")
    for token, reason in (("not-a-jwt", "malformed_token"), (no_kid, "missing_kid")):
        with pytest.raises(AuthenticationError) as exc:
            _verifier(MemoryJwks(key)).verify(token)
        assert exc.value.reason == reason


def test_key_rotation_is_picked_up_and_refresh_is_throttled() -> None:
    old, new = LocalSigningKey(), LocalSigningKey()
    source = MemoryJwks(old)
    now = [1000.0]
    verifier = _verifier(source, clock=lambda: now[0])
    verifier.verify(_token(old))
    assert source.fetches == 1

    # El proveedor publica una clave nueva; antes del intervalo mínimo no recargo.
    source.keys = [old, new]
    with pytest.raises(AuthenticationError) as exc:
        verifier.verify(_token(new))
    assert exc.value.reason == "unknown_key"
    assert source.fetches == 1

    now[0] += 31
    assert verifier.verify(_token(new)).subject == "alice"
    assert source.fetches == 2

    # Retiro la clave anterior: al vencer la caché, sus tokens dejan de valer.
    source.keys = [new]
    now[0] += 601
    with pytest.raises(AuthenticationError):
        verifier.verify(_token(old))


def test_unknown_kid_floods_do_not_refetch_every_time() -> None:
    key = LocalSigningKey()
    source = MemoryJwks(key)
    verifier = _verifier(source, clock=lambda: 5000.0)
    verifier.verify(_token(key))
    for _ in range(20):
        with pytest.raises(AuthenticationError):
            verifier.verify(_token(LocalSigningKey()))
    assert source.fetches == 1


def test_api_rejects_missing_expired_and_forged_tokens(client, signing_key, token_for) -> None:
    cases = {
        "missing": {},
        "wrong_scheme": {"Authorization": f"Basic {token_for('alice')}"},
        "expired": {"Authorization": f"Bearer {token_for('alice', now=time.time() - 7200, lifetime_seconds=60)}"},
        "forged": {"Authorization": f"Bearer {_token(LocalSigningKey(kid=signing_key.kid))}"},
        "garbage": {"Authorization": "Bearer abc.def.ghi"},
    }
    for name, headers in cases.items():
        res = client.get("/v1/me", headers=headers)
        assert res.status_code == 401, name
        assert res.headers["WWW-Authenticate"].startswith("Bearer"), name
        assert "token" not in res.json()["detail"].lower() or res.json()["detail"] in ("Missing access token.", "Invalid access token.")
