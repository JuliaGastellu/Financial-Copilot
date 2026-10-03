"""Verifico que Compose y .env.example usen variables que Settings consume."""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from app.core.config import Settings

ROOT = Path(__file__).resolve().parents[1]
SETTINGS_ENV_NAMES = {name.upper() for name in Settings.model_fields}
SECRET_NAMES = {"OPENAI_API_KEY", "PRIVACY_HASH_KEY", "POSTGRES_PASSWORD"}
COMPOSE_ONLY_NAMES = {"POSTGRES_PASSWORD"}


def _compose_environment() -> dict[str, str]:
    text = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    return dict(re.findall(r"^\s*-\s*([A-Z_][A-Z0-9_]*)=(.*)$", text, flags=re.MULTILINE))


def _env_example() -> dict[str, str]:
    values: dict[str, str] = {}
    for line in (ROOT / ".env.example").read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        key, _, value = line.partition("=")
        values[key.strip()] = value.strip()
    return values


def test_compose_variables_are_consumed_by_settings() -> None:
    env = _compose_environment()
    assert env, "No encontré variables de entorno en docker-compose.yml"
    unknown = sorted(set(env) - SETTINGS_ENV_NAMES)
    assert unknown == []


def test_compose_storage_resolves_inside_volume(monkeypatch: pytest.MonkeyPatch) -> None:
    for key, value in _compose_environment().items():
        monkeypatch.setenv(key, value)
    settings = Settings(_env_file=None)
    # La base relacional es PostgreSQL en el servicio db; el índice queda en el volumen.
    assert settings.resolved_database_url().startswith("postgresql+psycopg://copilot:")
    assert settings.resolved_database_url().endswith("@db:5432/copilot")
    assert settings.resolved_chroma_dir().as_posix() == "/app/data/chroma"
    assert settings.offline_mode is True


def test_compose_has_no_hardcoded_database_password() -> None:
    text = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    assert "${POSTGRES_PASSWORD:?" in text
    assert "POSTGRES_PASSWORD: ${POSTGRES_PASSWORD" in text


def test_env_example_uses_known_variables_without_secrets() -> None:
    env = _env_example()
    unknown = sorted(set(env) - SETTINGS_ENV_NAMES - COMPOSE_ONLY_NAMES)
    assert unknown == []
    for name in SECRET_NAMES:
        assert not env.get(name), f"{name} no debe tener valor en .env.example"


def test_env_example_parses_into_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in SETTINGS_ENV_NAMES:
        monkeypatch.delenv(name, raising=False)
    settings = Settings(_env_file=ROOT / ".env.example")
    assert settings.offline_mode is True
    assert settings.openai_api_key is None
    assert settings.allowed_origins == ["http://127.0.0.1:8000"]
    assert settings.database_url is None
    assert settings.oidc_jwks_url == "file:data/dev_identity/jwks.json"
    settings.validate_runtime()
