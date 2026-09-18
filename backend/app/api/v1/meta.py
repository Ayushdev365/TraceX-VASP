"""Meta endpoints: health and public configuration.

``/health`` reports each dependency separately rather than a single boolean. During a live
demo the useful question is never "is it up" but "which piece is missing" — an absent
Etherscan key and an unreachable database are very different problems.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter

from app.config import Settings, get_settings
from app.database.session import ping
from app.schemas.common import DependencyHealth, HealthResponse

router = APIRouter(tags=["meta"])


async def _database_health(settings: Settings) -> DependencyHealth:
    """Probe the database for real rather than reporting whether a URL is present.

    A configured-but-unreachable Supabase instance and a healthy one are very different
    situations on demo day, and only a query can tell them apart.
    """
    reachable = await ping()
    if not settings.database_url:
        return DependencyHealth(
            name="database",
            status="ok" if reachable else "unavailable",
            detail=(
                "DATABASE_URL is empty; using the local SQLite development fallback. "
                "Set DATABASE_URL before processing any real case data."
            ),
        )
    return DependencyHealth(
        name="database",
        status="ok" if reachable else "unavailable",
        detail=None if reachable else "The configured database did not answer a test query.",
    )


def _dependencies(settings: Settings) -> list[DependencyHealth]:
    """Configuration snapshot for the non-database dependencies.

    Live connectivity probes for the chain providers arrive with their adapters in
    Phase 3/4; until then, claiming a provider is healthy would be an unsupported claim.
    """
    return [
        DependencyHealth(
            name="ethereum_provider",
            status="ok" if settings.etherscan_api_key else "not_configured",
            detail=(
                None
                if settings.etherscan_api_key
                else "ETHERSCAN_API_KEY is empty; Ethereum traces will run in mock/demo mode."
            ),
        ),
        DependencyHealth(
            name="tron_provider",
            status="ok" if settings.trongrid_api_key else "not_configured",
            detail=(
                None
                if settings.trongrid_api_key
                else "TRONGRID_API_KEY is empty; Tron traces will run in mock/demo mode."
            ),
        ),
        DependencyHealth(
            name="auth",
            status="ok" if settings.auth_enabled else "not_configured",
            detail=(
                None
                if settings.auth_enabled
                else "DEMO_API_KEY is empty; the API is open on this instance (development only)."
            ),
        ),
    ]


@router.get(
    "/health",
    response_model=HealthResponse,
    summary="Liveness and dependency status",
)
async def health() -> HealthResponse:
    settings = get_settings()
    dependencies = [await _database_health(settings), *_dependencies(settings)]
    # "degraded" only when something is broken, not merely unconfigured: an absent provider
    # key is an honest gap, an unreachable database is a fault.
    is_degraded = any(dep.status in {"unavailable", "degraded"} for dep in dependencies)
    return HealthResponse(
        status="degraded" if is_degraded else "ok",
        engine_version=settings.engine_version,
        app_env=settings.app_env,
        time=datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z"),
        dependencies=dependencies,
    )


@router.get(
    "/meta/config",
    summary="Public configuration (hop limits, score bands, disclaimers)",
)
async def public_config() -> dict[str, Any]:
    """Non-secret knobs the frontend needs.

    The frontend reads its hop limits, score bands and disclaimer strings from here rather
    than hardcoding them, so the labelling policy stays identical across UI, reports and
    disclosure drafts (DPRD sec.48 task 36).
    """
    return get_settings().public_config()
