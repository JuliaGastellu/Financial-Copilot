from __future__ import annotations

from pathlib import Path
from typing import Literal
from urllib.parse import urlparse

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class InsecureConfigurationError(RuntimeError):
    """La configuración no es apta para el entorno declarado."""


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    environment: Literal["local", "test", "production"] = "local"

    data_dir: Path = Field(default_factory=lambda: _default_data_dir())
    # URL de SQLAlchemy. Si falta, uso SQLite en DATA_DIR/app.db (solo local y test).
    database_url: str | None = None
    sqlite_path: Path | None = None
    auto_migrate: bool = True
    chroma_dir: Path | None = None

    # Identidad gestionada (OIDC). Verifico tokens de acceso JWT contra el JWKS del emisor.
    oidc_issuer: str | None = None
    oidc_audience: str | None = None
    oidc_jwks_url: str | None = None
    oidc_algorithms: list[str] = Field(default_factory=lambda: ["RS256"])
    oidc_leeway_seconds: int = Field(default=30, ge=0, le=120)
    oidc_max_token_age_seconds: int = Field(default=3600, ge=60, le=86400)
    jwks_cache_seconds: int = Field(default=600, ge=30)
    jwks_min_refresh_seconds: int = Field(default=30, ge=1)

    # Clave para seudonimizar identidades en recibos de borrado.
    privacy_hash_key: str | None = None

    plan_retention_days: int = Field(default=730, ge=1)
    audit_retention_days: int = Field(default=365, ge=1)
    backup_retention_days: int = Field(default=35, ge=1)
    max_goals_per_user: int = Field(default=50, ge=1, le=500)
    max_plans_listed: int = Field(default=50, ge=1, le=200)

    openai_api_key: str | None = None
    openai_model: str = "gpt-4o-mini"
    offline_mode: bool = False

    rag_chunk_size: int = 900
    rag_chunk_overlap: int = 120
    rag_top_k: int = 6
    # Umbral de similitud coseno para proponer candidatos. La decisión de responder es léxica (app/rag/answer.py).
    rag_min_relevance: float = 0.1
    # Umbral de coincidencia de términos para la búsqueda alternativa sin índice.
    rag_min_keyword_overlap: float = 0.5
    embedding_model: str = "text-embedding-3-small"
    embedding_dimension: int = Field(default=1536, ge=8, le=4096)

    # Explicación de planes. Deshabilitada por defecto: el cálculo no depende del proveedor.
    explanation_provider: Literal["disabled", "openai_compatible"] = "disabled"
    explanation_base_url: str = "https://api.openai.com/v1"
    explanation_model: str = "gpt-4o-mini"
    explanation_timeout_seconds: float = Field(default=15.0, gt=0, le=60)
    explanation_max_retries: int = Field(default=2, ge=0, le=3)
    explanation_max_input_tokens: int = Field(default=3000, ge=200, le=20000)
    explanation_max_output_tokens: int = Field(default=700, ge=100, le=4000)
    explanation_daily_quota: int = Field(default=20, ge=0, le=1000)
    explanation_daily_token_budget: int = Field(default=40000, ge=0)

    # Lista JSON de orígenes permitidos. En producción exijo orígenes explícitos con https.
    allowed_origins: list[str] = Field(default_factory=lambda: ["http://127.0.0.1:8000", "http://localhost:8000"])

    # Limito solicitudes por minuto y por cuenta (o IP sin cuenta); uso rate_limit_enabled para desactivarlo.
    rate_limit_enabled: bool = True
    rate_limit_default: str = "60/minute"
    rate_limit_writes: str = "20/minute"
    rate_limit_query: str = "20/minute"
    rate_limit_plans: str = "20/minute"
    rate_limit_privacy: str = "5/minute"
    rate_limit_explanations: str = "6/minute"

    def resolved_sqlite_path(self) -> Path:
        return self.sqlite_path or (self.data_dir / "app.db")

    def resolved_database_url(self) -> str:
        if self.database_url:
            return self.database_url
        return f"sqlite:///{self.resolved_sqlite_path().as_posix()}"

    def resolved_chroma_dir(self) -> Path:
        return self.chroma_dir or (self.data_dir / "chroma")

    def insecure_settings(self) -> list[str]:
        """Enumero problemas que impiden arrancar en producción."""
        problems: list[str] = []
        url = self.resolved_database_url()
        if not url.startswith("postgresql"):
            problems.append("DATABASE_URL must point to PostgreSQL.")
        for name, value in (("OIDC_ISSUER", self.oidc_issuer), ("OIDC_JWKS_URL", self.oidc_jwks_url)):
            if not value or urlparse(value).scheme != "https":
                problems.append(f"{name} must be an https URL.")
        if not self.oidc_audience:
            problems.append("OIDC_AUDIENCE is required.")
        if any(a.upper().startswith("HS") or a.lower() == "none" for a in self.oidc_algorithms):
            problems.append("OIDC_ALGORITHMS must only contain asymmetric algorithms.")
        if not self.privacy_hash_key or len(self.privacy_hash_key) < 32:
            problems.append("PRIVACY_HASH_KEY must have at least 32 characters.")
        if not self.allowed_origins:
            problems.append("ALLOWED_ORIGINS must list the web origins explicitly.")
        for origin in self.allowed_origins:
            parsed = urlparse(origin)
            if origin == "*" or parsed.scheme != "https" or not parsed.netloc or parsed.path not in ("", "/"):
                problems.append(f"ALLOWED_ORIGINS entry is not an explicit https origin: {origin!r}")
        if not self.rate_limit_enabled:
            problems.append("RATE_LIMIT_ENABLED must be true.")
        if self.auto_migrate:
            problems.append("AUTO_MIGRATE must be false; apply migrations as a separate step.")
        if self.explanation_provider != "disabled" and urlparse(self.explanation_base_url).scheme != "https":
            problems.append("EXPLANATION_BASE_URL must use https.")
        return problems

    def validate_runtime(self) -> None:
        if self.environment == "production":
            problems = self.insecure_settings()
            if problems:
                raise InsecureConfigurationError("Refusing to start: " + " ".join(problems))
        elif "*" in self.allowed_origins:
            raise InsecureConfigurationError("ALLOWED_ORIGINS cannot contain '*'.")


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _default_data_dir() -> Path:
    return _project_root() / "data"


settings = Settings()
