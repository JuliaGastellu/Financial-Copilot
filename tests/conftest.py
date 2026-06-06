from __future__ import annotations

import sys
from pathlib import Path

root = Path(__file__).resolve().parents[1]
if str(root) not in sys.path:
    sys.path.insert(0, str(root))

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app


@pytest.fixture()
def test_client(tmp_path: Path) -> TestClient:
    settings = Settings(
        environment="test",
        data_dir=tmp_path / "data",
        sqlite_path=tmp_path / "data" / "app.db",
        chroma_dir=tmp_path / "data" / "chroma",
        offline_mode=True,
        rate_limit_enabled=False,
    )
    app = create_app(settings_override=settings)
    with TestClient(app) as client:
        yield client
