"""Alembic environment — async engine, URL resolved from the application settings.

The connection string is never stored in ``alembic.ini``; it comes from ``DATABASE_URL`` via
``app.database.session.resolve_database_url``, so migrations and the running app can never
target different databases.
"""

from __future__ import annotations

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import Connection, pool
from sqlalchemy.ext.asyncio import async_engine_from_config

from app.config import get_settings
from app.database.models import Base
from app.database.session import is_sqlite, resolve_database_url

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

_url = resolve_database_url(get_settings().database_url)
config.set_main_option("sqlalchemy.url", _url)


def _configure(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
        compare_server_default=True,
        # SQLite cannot ALTER most things in place; batch mode rewrites the table instead.
        # Harmless on PostgreSQL, essential for the local fallback.
        render_as_batch=is_sqlite(_url),
    )


def run_migrations_offline() -> None:
    """Emit SQL to stdout without connecting — useful for review before a Supabase apply."""
    context.configure(
        url=_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=is_sqlite(_url),
    )
    with context.begin_transaction():
        context.run_migrations()


def _do_run_migrations(connection: Connection) -> None:
    _configure(connection)
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(_do_run_migrations)
    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
