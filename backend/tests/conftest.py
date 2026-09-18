"""Shared pytest fixtures.

Tests run against a deterministic environment: no real provider keys, and a throwaway
in-file SQLite database per test. That means a test can never hit a live blockchain API or a
real Supabase instance, and no test depends on another test's data.
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

# Set before any app import so get_settings() caches a known configuration.
os.environ.setdefault("APP_ENV", "development")
os.environ.setdefault("LOG_LEVEL", "WARNING")
os.environ.setdefault("DEMO_API_KEY", "")
os.environ.setdefault("DATABASE_URL", "")
os.environ.setdefault("ETHERSCAN_API_KEY", "")
os.environ.setdefault("TRONGRID_API_KEY", "")
os.environ.setdefault("BITQUERY_API_KEY", "")

DATA_DIR = Path(__file__).resolve().parents[2] / "data" / "labels"


async def _create_schema(db_path: Path) -> None:
    """Create every table from the ORM metadata in a throwaway database."""
    from app.database.models import Base

    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}", poolclass=NullPool)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    await engine.dispose()


@pytest.fixture(scope="session")
def api_prefix() -> str:
    from app.config import get_settings

    return get_settings().api_prefix


@pytest.fixture
async def db_session(tmp_path: Path) -> AsyncIterator[AsyncSession]:
    """A fresh database per test, created from the ORM metadata.

    Uses ``create_all`` rather than running Alembic: the migration is verified separately
    (``test_migrations.py``), and paying its cost per test would slow the suite for no extra
    coverage.
    """
    db_path = tmp_path / "test.db"
    await _create_schema(db_path)

    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}", poolclass=NullPool)
    maker = async_sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)
    async with maker() as session:
        yield session

    await engine.dispose()


@pytest.fixture
def client(tmp_path: Path) -> Iterator[TestClient]:
    """App client backed by its own throwaway database.

    The session dependency is overridden rather than reconfigured globally, so the engine
    cache in ``app.database.session`` stays untouched between tests.
    """
    from app.deps import get_session
    from app.main import create_app

    db_path = tmp_path / "api.db"
    asyncio.run(_create_schema(db_path))

    # NullPool: the schema was created on a different event loop, and a pooled aiosqlite
    # connection must not be shared across loops.
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}", poolclass=NullPool)
    maker = async_sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)

    async def _override() -> AsyncIterator[AsyncSession]:
        async with maker() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    app = create_app()
    app.dependency_overrides[get_session] = _override

    with TestClient(app) as test_client:
        yield test_client

    app.dependency_overrides.clear()
    asyncio.run(engine.dispose())
