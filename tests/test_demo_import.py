from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
from pathlib import Path

from app.data.demo_import import legacy_profile_to_v1, read_legacy_profiles

ROOT = Path(__file__).resolve().parents[1]
LEGACY = {
    "user_id": "demo-user",
    "country": "US",
    "risk_tolerance": "medium",
    "cashflow": {"monthly_income": 5000, "monthly_expenses": 3800},
    "assets": [{"name": "Checking", "category": "cash", "value": 4000.0, "liquidity": "high"}],
    "liabilities": [{"name": "Card", "balance": 1200.0, "apr": 22.0, "minimum_payment": 60}],
    "goals": [{"name": "Fund", "target_amount": 12000, "current_amount": 0, "horizon_months": 12, "priority": "high"}],
    "preferences": {"currency": "USD"},
}


def _legacy_db(path: Path) -> Path:
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE profiles (user_id TEXT PRIMARY KEY, profile_json TEXT, created_at TEXT, updated_at TEXT)")
    conn.execute("INSERT INTO profiles VALUES (?, ?, '', '')", ("demo-user", json.dumps(LEGACY)))
    conn.execute("INSERT INTO profiles VALUES (?, ?, '', '')", ("someone-else", json.dumps({**LEGACY, "user_id": "someone-else"})))
    conn.commit()
    conn.close()
    return path


def test_conversion_to_v1_contract() -> None:
    profile, goals = legacy_profile_to_v1(LEGACY)
    assert profile["currency"] == "USD"
    assert profile["cashflows"][0]["monthly_income"] == "5000.00"
    assert profile["liabilities"][0]["minimum_payment"] == {"amount": "60.00", "currency": "USD"}
    assert "user_id" not in profile
    assert str(goals[0]["target"]["amount"]) == "12000.00"


def test_only_named_profiles_are_read(tmp_path) -> None:
    db = _legacy_db(tmp_path / "legacy.db")
    assert set(read_legacy_profiles(db, ["demo-user"])) == {"demo-user"}


def test_script_requires_confirmation_and_prints_only_counts(tmp_path) -> None:
    db = _legacy_db(tmp_path / "legacy.db")
    base = [
        sys.executable, str(ROOT / "scripts" / "import_local_demo.py"),
        "--sqlite", str(db), "--legacy-user", "demo-user", "--issuer", "https://i", "--subject", "s",
    ]
    refused = subprocess.run(base, capture_output=True, text=True, cwd=ROOT, timeout=120)
    assert refused.returncode != 0 and "fictitious" in refused.stderr
    dry = subprocess.run(base + ["--i-confirm-fictitious-data"], capture_output=True, text=True, cwd=ROOT, timeout=120)
    assert dry.returncode == 0, dry.stderr
    assert dry.stdout.strip() == "profiles_found=1 goals=1 apply=False"
    assert "Checking" not in dry.stdout and "5000" not in dry.stdout
