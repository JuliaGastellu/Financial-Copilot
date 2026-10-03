from __future__ import annotations

from alembic import context

from app.core.config import Settings
from app.db.engine import build_engine
from app.db.schema import metadata

config = context.config


def _url() -> str:
    return config.attributes.get("database_url") or Settings().resolved_database_url()


def run_migrations_offline() -> None:
    context.configure(url=_url(), target_metadata=metadata, literal_binds=True, render_as_batch=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    shared = config.attributes.get("connection")
    if shared is not None:
        context.configure(connection=shared, target_metadata=metadata, render_as_batch=True)
        with context.begin_transaction():
            context.run_migrations()
        return
    url = _url()
    engine = build_engine(url) if url.startswith("sqlite") else build_engine(url).execution_options()
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=metadata, render_as_batch=True)
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
