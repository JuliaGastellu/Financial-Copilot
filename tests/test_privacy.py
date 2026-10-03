"""Exportación, borrado con evidencia, retención, auditoría sin contenido y restore de backup."""
from __future__ import annotations

import json
import shutil
from datetime import timedelta
from pathlib import Path

import pytest
from sqlalchemy import func, select

from app.data.accounts import utc_now
from app.data.privacy import PrivacyRepository, subject_hash, privacy_key
from app.db.engine import build_engine
from app.db.schema import audit_events, deletion_receipts, goals, plans, profiles, users
from tests.v1_payloads import idem, goal_v1, profile_v1


def _seed(client, headers) -> dict:
    assert client.put("/v1/profile", json=profile_v1(), headers=headers).status_code == 200
    goal = client.post("/v1/goals", json=goal_v1("Private goal", 4321), headers=headers).json()
    plan = client.post("/v1/plans", json={}, headers=idem(headers)).json()
    return {"goal": goal, "plan": plan}


def _counts(engine, user_id: str) -> dict[str, int]:
    with engine.connect() as conn:
        return {
            "users": conn.execute(select(func.count()).select_from(users).where(users.c.id == user_id)).scalar_one(),
            "profiles": conn.execute(select(func.count()).select_from(profiles).where(profiles.c.user_id == user_id)).scalar_one(),
            "goals": conn.execute(select(func.count()).select_from(goals).where(goals.c.user_id == user_id)).scalar_one(),
            "plans": conn.execute(select(func.count()).select_from(plans).where(plans.c.user_id == user_id)).scalar_one(),
        }


def test_export_contains_all_own_data(client, auth):
    h = auth("exporter")
    seeded = _seed(client, h)
    res = client.get("/v1/me/export", headers=h)
    assert res.status_code == 200
    assert res.headers["Cache-Control"] == "no-store"
    data = res.json()
    assert data["export_format_version"] == 1
    assert data["user"]["subject"] == "exporter"
    assert data["profile"]["data"]["currency"] == "USD"
    assert [g["id"] for g in data["goals"]] == [seeded["goal"]["id"]]
    assert [p["id"] for p in data["plans"]] == [seeded["plan"]["id"]]
    assert {e["action"] for e in data["audit_events"]} >= {"profile.upsert", "goal.create", "plan.create"}


def test_delete_removes_personal_rows_and_returns_evidence(client, auth):
    h = auth("leaver")
    _seed(client, h)
    user_id = client.get("/v1/me", headers=h).json()["user_id"]
    engine = client.app.state.container.engine
    assert _counts(engine, user_id) == {"users": 1, "profiles": 1, "goals": 1, "plans": 1}

    res = client.delete("/v1/me", headers=h)
    assert res.status_code == 200
    evidence = res.json()["evidence"]
    assert evidence["relational_database"]["deleted"] == {
        "explanation_usage": 0, "plan_explanations": 0, "idempotency_keys": 1, "progress_entries": 0, "scenarios": 0,
        "plans": 1, "goals": 1, "profiles": 1, "users": 1,
    }
    assert set(evidence["relational_database"]["remaining"].values()) == {0}
    assert evidence["vector_store"]["personal_records"] == 0
    assert "backups" in evidence and "application_logs" in evidence
    assert _counts(engine, user_id) == {"users": 0, "profiles": 0, "goals": 0, "plans": 0}

    with engine.connect() as conn:
        receipt = conn.execute(select(deletion_receipts)).mappings().one()
    settings = client.app.state.container.settings
    assert receipt["subject_hash"] == subject_hash(privacy_key(settings), settings.oidc_issuer, "leaver")
    assert "leaver" not in json.dumps(receipt["evidence"])

    # Iniciar sesión de nuevo crea una cuenta vacía, sin datos anteriores.
    assert client.get("/v1/me", headers=h).json()["user_id"] != user_id
    assert client.get("/v1/goals", headers=h).json() == []
    assert client.get("/v1/profile", headers=h).status_code == 404


def test_audit_events_never_store_financial_content(client, auth):
    h = auth("auditee")
    _seed(client, h)
    with client.app.state.container.engine.connect() as conn:
        rows = conn.execute(select(audit_events)).mappings().all()
    assert rows
    # El esquema no tiene columnas para importes ni textos libres.
    assert set(audit_events.c.keys()) == {"id", "occurred_at", "user_id", "action", "resource_type", "resource_id", "outcome", "request_id"}
    for row in rows:
        assert row["action"] in {"profile.upsert", "goal.create", "plan.create"}
        assert row["resource_type"] in {"profile", "goal", "plan"}
        assert row["outcome"] == "success"
        for key in ("id", "user_id"):
            assert len(row[key]) == 36
        assert row["resource_id"] is None or len(row["resource_id"]) == 36
    assert "Private goal" not in json.dumps([dict(r) for r in rows], default=str)


def test_retention_removes_only_expired_records(client, auth):
    h = auth("retained")
    _seed(client, h)
    container = client.app.state.container
    repo: PrivacyRepository = container.privacy
    settings = container.settings
    # Una segunda versión deja la primera como reemplazada.
    assert client.post("/v1/plans", json={}, headers=idem(h)).status_code == 201
    assert repo.apply_retention() == {"plans": 0, "audit_events": 0, "deletion_receipts": 0, "idempotency_keys": 0}
    later = utc_now() + timedelta(days=settings.plan_retention_days + 1)
    removed = repo.apply_retention(now=later)
    # Solo borro la versión reemplazada; el plan vigente se conserva.
    assert removed["plans"] == 1
    assert removed["idempotency_keys"] == 2
    assert client.get("/v1/plans/current", headers=h).status_code == 200
    assert removed["audit_events"] >= 3
    # Perfil y metas siguen hasta que la persona los borre.
    assert client.get("/v1/profile", headers=h).status_code == 200


def test_restore_from_backup_reapplies_deletions(client, auth, test_settings, tmp_path: Path):
    if not test_settings.resolved_database_url().startswith("sqlite"):
        pytest.skip("En PostgreSQL verifico el restore con pg_dump/pg_restore en test_postgres_backup_restore_reapplies_deletions.")
    db_path = Path(test_settings.resolved_database_url().split("///", 1)[1])
    keep, leave = auth("keeper"), auth("restored-leaver")
    _seed(client, keep)
    _seed(client, leave)
    backup = tmp_path / "backup.db"
    engine = client.app.state.container.engine
    with engine.connect() as conn:
        conn.exec_driver_sql(f"VACUUM INTO '{backup.as_posix()}'")

    assert client.delete("/v1/me", headers=leave).status_code == 200
    receipts = client.app.state.container.privacy.export_receipts()
    assert len(receipts) == 1

    # Restauro el backup en una copia y compruebo que los datos borrados vuelven a aparecer.
    restored_path = tmp_path / "restored.db"
    shutil.copy(backup, restored_path)
    restored = build_engine(f"sqlite:///{restored_path.as_posix()}")
    with restored.connect() as conn:
        assert conn.execute(select(func.count()).select_from(users)).scalar_one() == 2
    repo = PrivacyRepository(restored, test_settings)
    result = repo.reapply_deletions(receipts)
    assert result == {"accounts_deleted_again": 1, "receipts_restored": 1}
    with restored.connect() as conn:
        subjects = [r.subject for r in conn.execute(select(users.c.subject))]
        assert subjects == ["keeper"]
        assert conn.execute(select(func.count()).select_from(goals)).scalar_one() == 1
    # Reaplicar es idempotente.
    assert repo.reapply_deletions(receipts) == {"accounts_deleted_again": 0, "receipts_restored": 0}
    restored.dispose()
    assert db_path.exists()


def test_reapply_does_not_delete_account_created_after_deletion(client, auth, test_settings):
    h = auth("returner")
    _seed(client, h)
    client.delete("/v1/me", headers=h)
    receipts = client.app.state.container.privacy.export_receipts()
    _seed(client, h)  # vuelve a registrarse después del borrado
    result = client.app.state.container.privacy.reapply_deletions(receipts)
    assert result["accounts_deleted_again"] == 0
    assert client.get("/v1/profile", headers=h).status_code == 200


def test_postgres_backup_restore_reapplies_deletions(test_settings, tmp_path):
    """Backup real con pg_dump y restore con pg_restore en una base desechable.

    Requiere TEST_DATABASE_URL y PG_DOCKER_CONTAINER (contenedor con las herramientas de PostgreSQL).
    """
    import os
    import subprocess

    from sqlalchemy import create_engine, text
    from sqlalchemy.engine import make_url

    from app.data.accounts import GoalRepository, ProfileRepository, UserRepository
    from app.db.engine import upgrade

    container = os.environ.get("PG_DOCKER_CONTAINER")
    base_url = os.environ.get("TEST_DATABASE_URL")
    if not (container and base_url):
        pytest.skip("Set TEST_DATABASE_URL and PG_DOCKER_CONTAINER to run the PostgreSQL restore check.")
    url = make_url(base_url)
    db_name = "copilot_restore_check"
    admin = create_engine(url, isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(text(f"DROP DATABASE IF EXISTS {db_name}"))
        conn.execute(text(f"CREATE DATABASE {db_name}"))
    target = url.set(database=db_name).render_as_string(hide_password=False)
    upgrade(target)
    engine = build_engine(target)
    keeper = UserRepository(engine).get_or_create("https://issuer", "keeper")
    leaver = UserRepository(engine).get_or_create("https://issuer", "leaver")
    for user in (keeper, leaver):
        ProfileRepository(engine).upsert(user.id, {"currency": "USD"}, base_currency="USD")
        GoalRepository(engine).create(user.id, {"name": "g", "currency": "USD", "target_amount": 1, "saved_amount": 0, "priority": "high"})

    def docker(*args: str) -> None:
        subprocess.run(["docker", "exec", container, *args], check=True, capture_output=True, timeout=120)

    docker("pg_dump", "-U", url.username, "-Fc", "-f", "/tmp/restore_check.dump", db_name)
    repo = PrivacyRepository(engine, test_settings)
    repo.erase(leaver.id, "https://issuer", "leaver")
    receipts = repo.export_receipts()
    engine.dispose()

    with admin.connect() as conn:
        conn.execute(text(f"DROP DATABASE {db_name}"))
        conn.execute(text(f"CREATE DATABASE {db_name}"))
    docker("pg_restore", "-U", url.username, "-d", db_name, "/tmp/restore_check.dump")
    restored = build_engine(target)
    with restored.connect() as conn:
        assert conn.execute(select(func.count()).select_from(users)).scalar_one() == 2
    result = PrivacyRepository(restored, test_settings).reapply_deletions(receipts)
    assert result == {"accounts_deleted_again": 1, "receipts_restored": 1}
    with restored.connect() as conn:
        assert [r.subject for r in conn.execute(select(users.c.subject))] == ["keeper"]
        assert conn.execute(select(func.count()).select_from(goals)).scalar_one() == 1
    restored.dispose()
    with admin.connect() as conn:
        conn.execute(text(f"DROP DATABASE {db_name}"))
    admin.dispose()
    docker("rm", "-f", "/tmp/restore_check.dump")
