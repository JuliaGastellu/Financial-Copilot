from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any, Callable, Iterator

root = Path(__file__).resolve().parents[1]
if str(root) not in sys.path:
    sys.path.insert(0, str(root))

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.auth.dev_identity import LocalSigningKey, issue_token, jwks
from app.core.config import Settings
from app.db.engine import build_engine, upgrade
from app.main import create_app

ISSUER = "https://identity.test.invalid/"
AUDIENCE = "financial-copilot-api"
TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")
_TABLES = "chunks, documents, deletion_receipts, audit_events, plans, goals, profiles, users"


class MemoryJwks:
    """Doble local del endpoint JWKS: permite rotar claves y cuenta descargas."""

    def __init__(self, *keys: LocalSigningKey) -> None:
        self.keys = list(keys)
        self.fetches = 0

    def fetch(self) -> dict[str, Any]:
        self.fetches += 1
        return jwks(*self.keys)


@pytest.fixture(scope="session")
def signing_key() -> LocalSigningKey:
    return LocalSigningKey()


@pytest.fixture(scope="session")
def _postgres_ready() -> bool:
    if TEST_DATABASE_URL:
        upgrade(TEST_DATABASE_URL)
    return bool(TEST_DATABASE_URL)


@pytest.fixture()
def database_url(tmp_path: Path, _postgres_ready: bool) -> str:
    if TEST_DATABASE_URL:
        engine = build_engine(TEST_DATABASE_URL)
        with engine.begin() as conn:
            conn.execute(text(f"TRUNCATE {_TABLES} CASCADE"))
        engine.dispose()
        return TEST_DATABASE_URL
    return f"sqlite:///{(tmp_path / 'data' / 'app.db').as_posix()}"


@pytest.fixture()
def test_settings(tmp_path: Path, database_url: str) -> Settings:
    return Settings(
        _env_file=None,
        environment="test",
        data_dir=tmp_path / "data",
        database_url=database_url,
        chroma_dir=tmp_path / "data" / "chroma",
        offline_mode=True,
        rate_limit_enabled=False,
        oidc_issuer=ISSUER,
        oidc_audience=AUDIENCE,
        oidc_jwks_url="https://identity.test.invalid/.well-known/jwks.json",
        allowed_origins=["http://127.0.0.1:8000"],
    )


@pytest.fixture()
def jwks_source(signing_key: LocalSigningKey) -> MemoryJwks:
    return MemoryJwks(signing_key)


@pytest.fixture()
def client(test_settings: Settings, jwks_source: MemoryJwks) -> Iterator[TestClient]:
    app = create_app(settings_override=test_settings, jwks_source=jwks_source)
    with TestClient(app) as c:
        yield c


# Mantengo el nombre anterior para las pruebas que no dependen de identidad.
@pytest.fixture()
def test_client(client: TestClient) -> TestClient:
    return client


@pytest.fixture()
def token_for(signing_key: LocalSigningKey) -> Callable[..., str]:
    def make(subject: str, **kwargs: Any) -> str:
        return issue_token(signing_key, issuer=ISSUER, audience=AUDIENCE, subject=subject, **kwargs)

    return make


@pytest.fixture()
def auth(token_for: Callable[..., str]) -> Callable[[str], dict[str, str]]:
    def headers(subject: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {token_for(subject)}"}

    return headers
