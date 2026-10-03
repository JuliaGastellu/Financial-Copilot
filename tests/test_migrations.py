from __future__ import annotations

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import insert, inspect
from sqlalchemy.exc import IntegrityError

from app.data.accounts import new_id, utc_now
from app.db.engine import build_engine, current_revision, downgrade, head_revision, upgrade
from app.db.schema import chunks, documents, goals, metadata, users


def test_migration_matches_schema_and_rolls_back(database_url) -> None:
    upgrade(database_url)
    engine = build_engine(database_url)
    try:
        assert current_revision(engine) == head_revision(database_url)
        with engine.connect() as conn:
            assert compare_metadata(MigrationContext.configure(conn), metadata) == []
        downgrade(database_url, "base")
        assert current_revision(engine) is None
        assert set(inspect(engine).get_table_names()) - {"alembic_version"} == set()
        upgrade(database_url)
        assert current_revision(engine) == head_revision(database_url)
    finally:
        engine.dispose()


def test_database_constraints_reject_invalid_rows(database_url) -> None:
    upgrade(database_url)
    engine = build_engine(database_url)
    now = utc_now()
    try:
        with engine.begin() as conn:
            conn.execute(insert(users).values(id="u-1", issuer="i", subject="s", created_at=now, last_seen_at=now))
        base_goal = dict(
            user_id="u-1", name="g", currency="USD", target_amount=1, saved_amount=0, priority="high", created_at=now, updated_at=now
        )
        for bad in ({"target_amount": -1}, {"priority": "urgent"}, {"horizon_months": 0}, {"user_id": "missing-user"}):
            with pytest.raises(IntegrityError):
                with engine.begin() as conn:
                    conn.execute(insert(goals).values(id=new_id(), **{**base_goal, **bad}))
        with pytest.raises(IntegrityError):
            with engine.begin() as conn:
                conn.execute(insert(users).values(id="u-2", issuer="i", subject="s", created_at=now, last_seen_at=now))
        with pytest.raises(IntegrityError):
            with engine.begin() as conn:
                conn.execute(insert(documents).values(id="d", corpus="private", title="t", content="c", sha256="x", created_at=now))
        with pytest.raises(IntegrityError):
            with engine.begin() as conn:
                conn.execute(insert(documents).values(id="d2", corpus="public", title="t", content="c", sha256="y", created_at=now))
                conn.execute(insert(chunks).values(id="c", document_id="d2", corpus="private", chunk_index=0, content="c", sha256="y"))
    finally:
        engine.dispose()


def test_concurrent_upgrades_are_serialized_on_postgres(database_url) -> None:
    """Varios workers con AUTO_MIGRATE no deben chocar al crear el esquema."""
    import threading

    from sqlalchemy import create_engine, text
    from sqlalchemy.engine import make_url

    if not database_url.startswith("postgresql"):
        pytest.skip("Advisory locks only apply to PostgreSQL.")
    url = make_url(database_url)
    admin = create_engine(url, isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(text("DROP DATABASE IF EXISTS copilot_race_check"))
        conn.execute(text("CREATE DATABASE copilot_race_check"))
    target = url.set(database="copilot_race_check").render_as_string(hide_password=False)
    errors: list[str] = []

    def run() -> None:
        try:
            upgrade(target)
        except Exception as exc:  # pragma: no cover - solo falla si vuelve el problema
            errors.append(type(exc).__name__)

    threads = [threading.Thread(target=run) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    engine = build_engine(target)
    try:
        assert errors == []
        assert current_revision(engine) == head_revision(target)
    finally:
        engine.dispose()
        with admin.connect() as conn:
            conn.execute(text("DROP DATABASE copilot_race_check"))
        admin.dispose()


def test_revision_ids_fit_alembic_version_column() -> None:
    from alembic.script import ScriptDirectory

    from app.db.engine import alembic_config

    script = ScriptDirectory.from_config(alembic_config("sqlite://"))
    # alembic_version.version_num es VARCHAR(32) en PostgreSQL.
    assert all(len(rev.revision) <= 32 for rev in script.walk_revisions())


def test_legacy_plans_are_versioned_by_migration_0002(database_url) -> None:
    from datetime import timedelta

    from sqlalchemy import text

    downgrade(database_url, "base")
    upgrade(database_url, "0001_accounts_and_planning")
    engine = build_engine(database_url)
    now = utc_now()
    try:
        with engine.begin() as conn:
            conn.execute(text("INSERT INTO users VALUES ('legacy-u', 'i', 'legacy', :n, :n)"), {"n": now})
            for i, pid in enumerate(("old-1", "old-2", "old-3")):
                conn.execute(
                    text(
                        "INSERT INTO plans (id, user_id, as_of, policy_version, inputs, result, created_at) "
                        "VALUES (:id, 'legacy-u', '2026-09-01', 'x', '{}', '{}', :t)"
                    ),
                    {"id": pid, "t": now + timedelta(seconds=i)},
                )
        upgrade(database_url)
        with engine.connect() as conn:
            rows = conn.execute(text("SELECT id, version, status, source FROM plans ORDER BY version")).all()
        assert [tuple(r) for r in rows] == [
            ("old-1", 1, "superseded", "legacy"),
            ("old-2", 2, "superseded", "legacy"),
            ("old-3", 3, "active", "legacy"),
        ]
    finally:
        engine.dispose()
        downgrade(database_url, "base")
        upgrade(database_url)
