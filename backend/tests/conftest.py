"""Shared pytest fixtures.

Tests run against a deterministic environment: no real provider keys, no database, so a
test can never accidentally hit a live blockchain API or a real Supabase instance.
"""

from __future__ import annotations

import os
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

# Set before any app import so get_settings() caches a known configuration.
os.environ.setdefault("APP_ENV", "development")
os.environ.setdefault("LOG_LEVEL", "WARNING")
os.environ.setdefault("DEMO_API_KEY", "")
os.environ.setdefault("DATABASE_URL", "")
os.environ.setdefault("ETHERSCAN_API_KEY", "")
os.environ.setdefault("TRONGRID_API_KEY", "")
os.environ.setdefault("BITQUERY_API_KEY", "")


@pytest.fixture(scope="session")
def client() -> Iterator[TestClient]:
    from app.main import create_app

    with TestClient(create_app()) as test_client:
        yield test_client


@pytest.fixture(scope="session")
def api_prefix() -> str:
    from app.config import get_settings

    return get_settings().api_prefix
