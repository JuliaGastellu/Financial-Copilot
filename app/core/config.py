from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    environment: Literal["local", "test"] = "local"

    data_dir: Path = Field(default_factory=lambda: _default_data_dir())
    sqlite_path: Path | None = None
    chroma_dir: Path | None = None
    chroma_collection: str = "financial_copilot_knowledge"

    openai_api_key: str | None = None
    openai_model: str = "gpt-4o-mini"
    offline_mode: bool = False

    rag_chunk_size: int = 900
    rag_chunk_overlap: int = 120
    rag_top_k: int = 6
    rag_min_relevance: float = 0.15

    # CORS: comma-separated or JSON list of allowed origins; "*" allows all
    allowed_origins: list[str] = Field(default_factory=lambda: ["*"])

    # Rate limiting (requests per minute per IP). Set to 0 to disable.
    rate_limit_enabled: bool = True
    rate_limit_recommendations: str = "10/minute"
    rate_limit_ingest: str = "5/minute"
    rate_limit_query: str = "20/minute"

    def resolved_sqlite_path(self) -> Path:
        return self.sqlite_path or (self.data_dir / "app.db")

    def resolved_chroma_dir(self) -> Path:
        return self.chroma_dir or (self.data_dir / "chroma")


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _default_data_dir() -> Path:
    import os
    if os.environ.get("VERCEL") == "1":
        return Path("/tmp/data")
    return _project_root() / "data"


settings = Settings()
