from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.auth.tokens import FileJwksSource, HttpJwksSource, build_jwks_source
from app.core.config import InsecureConfigurationError, Settings
from app.main import create_app

SECURE = {
    "environment": "production",
    "database_url": "postgresql+psycopg://app@db.internal/copilot",
    "oidc_issuer": "https://login.example.com/",
    "oidc_audience": "financial-copilot-api",
    "oidc_jwks_url": "https://login.example.com/.well-known/jwks.json",
    "privacy_hash_key": "x" * 40,
    "allowed_origins": ["https://app.example.com"],
    "auto_migrate": False,
}


def _settings(**overrides) -> Settings:
    return Settings(_env_file=None, **{**SECURE, **overrides})


def test_secure_production_settings_pass() -> None:
    assert _settings().insecure_settings() == []
    _settings().validate_runtime()


@pytest.mark.parametrize(
    "overrides",
    [
        {"database_url": None},
        {"database_url": "sqlite:///data/app.db"},
        {"oidc_issuer": None},
        {"oidc_issuer": "http://login.example.com/"},
        {"oidc_audience": None},
        {"oidc_jwks_url": "file:jwks.json"},
        {"oidc_algorithms": ["HS256"]},
        {"privacy_hash_key": None},
        {"privacy_hash_key": "short"},
        {"allowed_origins": ["*"]},
        {"allowed_origins": []},
        {"allowed_origins": ["http://app.example.com"]},
        {"allowed_origins": ["https://app.example.com/path"]},
        {"rate_limit_enabled": False},
        {"auto_migrate": True},
    ],
)
def test_insecure_production_settings_refuse_to_start(overrides) -> None:
    with pytest.raises(InsecureConfigurationError):
        create_app(settings_override=_settings(**overrides))


def test_wildcard_cors_is_refused_everywhere() -> None:
    with pytest.raises(InsecureConfigurationError):
        Settings(_env_file=None, environment="local", allowed_origins=["*"]).validate_runtime()


def test_jwks_sources_by_environment(tmp_path) -> None:
    assert isinstance(build_jwks_source(_settings()), HttpJwksSource)
    local = Settings(_env_file=None, environment="local", oidc_jwks_url=f"file:{tmp_path / 'jwks.json'}")
    assert isinstance(build_jwks_source(local), FileJwksSource)
    with pytest.raises(ValueError):
        build_jwks_source(_settings(oidc_jwks_url="http://login.example.com/jwks"))


def test_production_hides_interactive_docs() -> None:
    app = create_app(settings_override=_settings(), jwks_source=object())  # type: ignore[arg-type]
    paths = {getattr(r, "path", None) for r in app.routes}
    assert "/docs" not in paths and "/openapi.json" not in paths


def test_cors_allows_only_configured_origins(client) -> None:
    allowed = client.options(
        "/v1/me",
        headers={"Origin": "http://127.0.0.1:8000", "Access-Control-Request-Method": "GET", "Access-Control-Request-Headers": "Authorization"},
    )
    assert allowed.headers.get("access-control-allow-origin") == "http://127.0.0.1:8000"
    assert "access-control-allow-credentials" not in allowed.headers
    denied = client.options("/v1/me", headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "GET"})
    assert "access-control-allow-origin" not in denied.headers


def test_v1_returns_503_when_authentication_is_not_configured(tmp_path) -> None:
    settings = Settings(_env_file=None, environment="test", data_dir=tmp_path, offline_mode=True, rate_limit_enabled=False)
    with TestClient(create_app(settings_override=settings)) as c:
        assert c.get("/v1/me").status_code == 503


def test_cors_preflight_allows_idempotency_key(client) -> None:
    # La aplicación web envía Idempotency-Key al crear recursos; sin esto el navegador bloquea la solicitud.
    res = client.options(
        "/v1/goals",
        headers={
            "Origin": "http://127.0.0.1:8000",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "authorization,content-type,idempotency-key",
        },
    )
    assert res.status_code == 200
    assert "idempotency-key" in res.headers["access-control-allow-headers"].lower()
    post = client.post("/v1/goals", json={}, headers={"Origin": "http://127.0.0.1:8000"})
    assert "idempotent-replayed" in post.headers.get("access-control-expose-headers", "").lower()
