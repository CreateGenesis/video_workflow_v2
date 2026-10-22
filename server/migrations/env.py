"""Alembic runs against CVGEN_DATABASE_URL. The schema lives in server/db.py."""

from __future__ import annotations

from alembic import context

from server.db import get_engine, metadata

config = context.config


def run_migrations_offline() -> None:
    from server.config import get_settings

    context.configure(url=get_settings().database_url, target_metadata=metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = config.attributes.get("connection")
    if connectable is not None:
        context.configure(connection=connectable, target_metadata=metadata, compare_type=True)
        with context.begin_transaction():
            context.run_migrations()
        return
    with get_engine().connect() as connection:
        context.configure(connection=connection, target_metadata=metadata, compare_type=True)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
