"""Async engine and session factory.

Async rather than sync because the chain adapters (Phase 3/4) are async HTTP clients: a
synchronous session inside an ``async def`` endpoint would block the event loop for the whole
duration of a trace.

Drivers: ``psycopg`` (v3, async-capable) for PostgreSQL/Supabase, ``aiosqlite`` for the local
fallback used when ``DATABASE_URL`` is unset. The fallback exists so the demo survives a venue
network failure — it is development-grade only, and production refuses to start without a real
``DATABASE_URL`` (see ``app/config.py``).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from functools import lru_cache
from pathlib import Path

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config import get_settings
from app.core.logging import get_logger

logger = get_logger(__name__)

#: Local fallback database file, relative to the backend package root.
SQLITE_PATH = Path(__file__).resolve().parents[2] / "var" / "vasptrace.db"


def resolve_database_url(raw: str | None) -> str:
    """Return an async-driver URL, or the SQLite fallback when nothing is configured.

    Accepts the sync-driver URLs people paste from Supabase's dashboard and rewrites them to
    their async equivalents, because getting this wrong produces a confusing
    ``MissingGreenlet`` error at the first query rather than at startup.
    """
    if not raw:
        SQLITE_PATH.parent.mkdir(parents=True, exist_ok=True)
        return f"sqlite+aiosqlite:///{SQLITE_PATH}"

    url = raw.strip()
    rewrites = {
        "postgres://": "postgresql+psycopg://",
        "postgresql://": "postgresql+psycopg://",
        "postgresql+psycopg2://": "postgresql+psycopg://",
        "sqlite://": "sqlite+aiosqlite://",
    }
    for prefix, replacement in rewrites.items():
        if url.startswith(prefix):
            return replacement + url[len(prefix) :]
    return url


def is_sqlite(url: str) -> bool:
    return url.startswith("sqlite")


@lru_cache(maxsize=1)
def get_engine() -> AsyncEngine:
    settings = get_settings()
    url = resolve_database_url(settings.database_url)

    if is_sqlite(url):
        engine = create_async_engine(url, echo=settings.db_echo, future=True)
    else:
        engine = create_async_engine(
            url,
            echo=settings.db_echo,
            future=True,
            # Supabase's pooler closes idle connections; pre-ping avoids handing a dead
            # connection to the first trace of the day.
            pool_pre_ping=True,
            pool_size=5,
            max_overflow=5,
            pool_recycle=300,
        )

    logger.info(
        "database_engine_created",
        extra={"dialect": engine.dialect.name, "fallback_sqlite": is_sqlite(url)},
    )
    return engine


@lru_cache(maxsize=1)
def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(
        bind=get_engine(),
        expire_on_commit=False,
        autoflush=False,
    )


async def session_scope() -> AsyncIterator[AsyncSession]:
    """Yield a session, committing on success and rolling back on any exception."""
    async with get_sessionmaker()() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def ping() -> bool:
    """True when the database answers a trivial query. Used by ``/health``."""
    from sqlalchemy import text

    try:
        async with get_engine().connect() as connection:
            await connection.execute(text("SELECT 1"))
        return True
    except Exception as exc:
        logger.warning("database_ping_failed", extra={"error_type": type(exc).__name__})
        return False


async def dispose_engine() -> None:
    """Close the pool on shutdown."""
    if get_engine.cache_info().currsize:
        await get_engine().dispose()
