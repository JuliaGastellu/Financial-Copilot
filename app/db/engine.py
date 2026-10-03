"""Creo motores de SQLAlchemy y aplico migraciones versionadas con Alembic."""
from __future__ import annotations

from pathlib import Path

from sqlalchemy import Engine, create_engine, event

ROOT = Path(__file__).resolve().parents[2]


def build_engine(url: str) -> Engine:
    if url.startswith("sqlite"):
        path = url.split("///", 1)[-1]
        if path and path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        engine = create_engine(url, connect_args={"check_same_thread": False})

        @event.listens_for(engine, "connect")
        def _enable_foreign_keys(dbapi_connection, _record) -> None:  # pragma: no cover - trivial
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys = ON")
            cursor.close()

        return engine
    return create_engine(url, pool_pre_ping=True)


def alembic_config(url: str):
    from alembic.config import Config

    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "migrations"))
    config.attributes["database_url"] = url
    return config


# Clave fija del advisory lock que serializa migraciones entre procesos en PostgreSQL.
_MIGRATION_LOCK_ID = 7_301_2026


def upgrade(url: str, revision: str = "head") -> None:
    from alembic import command

    config = alembic_config(url)
    if not url.startswith("postgresql"):
        command.upgrade(config, revision)
        return
    # Varios workers pueden arrancar a la vez: solo uno migra y los demás esperan el lock.
    engine = build_engine(url)
    try:
        with engine.connect() as conn:
            conn.exec_driver_sql(f"SELECT pg_advisory_lock({_MIGRATION_LOCK_ID})")
            try:
                config.attributes["connection"] = conn
                command.upgrade(config, revision)
                conn.commit()
            except Exception:
                # Descarto la transacción fallida para poder liberar el lock y conservar el error original.
                conn.rollback()
                raise
            finally:
                conn.exec_driver_sql(f"SELECT pg_advisory_unlock({_MIGRATION_LOCK_ID})")
                conn.commit()
    finally:
        engine.dispose()


def downgrade(url: str, revision: str = "base") -> None:
    from alembic import command

    command.downgrade(alembic_config(url), revision)


def current_revision(engine: Engine) -> str | None:
    from alembic.runtime.migration import MigrationContext

    with engine.connect() as conn:
        return MigrationContext.configure(conn).get_current_revision()


def head_revision(url: str) -> str | None:
    from alembic.script import ScriptDirectory

    return ScriptDirectory.from_config(alembic_config(url)).get_current_head()
