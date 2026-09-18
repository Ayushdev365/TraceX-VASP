"""Alembic migration verification.

The test suite builds its schema with ``create_all``, so without this file the migration
could silently drift from the models — and the migration is what actually runs against
Supabase. These tests keep the two in agreement.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect

BACKEND_DIR = Path(__file__).resolve().parents[2]


def run_alembic(*args: str, db_path: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=BACKEND_DIR,
        capture_output=True,
        text=True,
        timeout=180,
        env={
            "PATH": "/usr/bin:/bin",
            "DATABASE_URL": f"sqlite:///{db_path}",
            "APP_ENV": "development",
            "LOG_LEVEL": "WARNING",
        },
        check=False,
    )


@pytest.fixture
def migrated_db(tmp_path: Path) -> Path:
    db_path = tmp_path / "migrated.db"
    result = run_alembic("upgrade", "head", db_path=db_path)
    assert result.returncode == 0, f"upgrade failed:\n{result.stderr}"
    return db_path


def test_upgrade_creates_every_table(migrated_db: Path) -> None:
    from app.database.models import Base

    engine = create_engine(f"sqlite:///{migrated_db}")
    actual = set(inspect(engine).get_table_names()) - {"alembic_version"}
    engine.dispose()

    assert actual == set(Base.metadata.tables)


def test_migration_matches_the_models(migrated_db: Path) -> None:
    """An empty autogenerate diff proves the migration and the ORM agree.

    If this fails, someone changed a model without generating a migration — which would work
    locally (tests use ``create_all``) and then break on Supabase.
    """
    result = run_alembic("check", db_path=migrated_db)
    assert result.returncode == 0, (
        "the models have drifted from the migration; run:\n"
        "  alembic revision --autogenerate -m '<describe the change>'\n\n"
        f"{result.stdout}\n{result.stderr}"
    )


def test_downgrade_removes_every_table(tmp_path: Path) -> None:
    db_path = tmp_path / "roundtrip.db"
    assert run_alembic("upgrade", "head", db_path=db_path).returncode == 0

    result = run_alembic("downgrade", "base", db_path=db_path)
    assert result.returncode == 0, f"downgrade failed:\n{result.stderr}"

    engine = create_engine(f"sqlite:///{db_path}")
    remaining = set(inspect(engine).get_table_names()) - {"alembic_version"}
    engine.dispose()

    assert remaining == set()


def test_honesty_constraints_survive_the_migration(migrated_db: Path) -> None:
    """The two constraints that protect the product's claims must exist in the real DDL.

    Verified against the migrated database rather than the models, because these are the
    ones that will be enforced in production.
    """
    engine = create_engine(f"sqlite:///{migrated_db}")
    names = {
        constraint["name"] for constraint in inspect(engine).get_check_constraints("vasp_addresses")
    }
    engine.dispose()

    assert "ck_vasp_addresses_verified_needs_date" in names
    assert "ck_vasp_addresses_demo_is_unverified" in names
