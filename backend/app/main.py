"""VASPTrace API — application entrypoint.

Automated Blockchain Intelligence & VASP Attribution Engine (SIH26182, Team TraceX).

Claim posture, enforced throughout the codebase and repeated in the OpenAPI description:
this service produces an investigative lead, not legal proof. Attribution scores are
explicitly-labelled heuristics, not calibrated probabilities. No beneficial-owner
identification and no freezing, blocking or live disclosure submission happens anywhere in
this system (DPRD sec.24, sec.37).

Run locally:
    uvicorn app.main:app --reload --port 8000
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.router import api_router
from app.config import LEAD_NOT_PROOF, SCORE_DISCLAIMER, get_settings
from app.core.errors import register_exception_handlers
from app.core.logging import configure_logging, get_logger
from app.core.middleware import RequestContextMiddleware
from app.database.session import dispose_engine

DESCRIPTION = f"""
Traces an unknown cryptocurrency wallet across a blockchain transaction graph, matches
visited addresses against a labelled VASP dataset, and returns ranked candidate
attributions with an explainable score breakdown, risk indicators, an evidence trail and
an investigation-ready report.

**{LEAD_NOT_PROOF}** {SCORE_DISCLAIMER}
"""


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Startup/shutdown. Settings are resolved here so a bad env fails at boot."""
    settings = get_settings()
    logger = get_logger(__name__)
    logger.info(
        "startup",
        extra={
            "app_env": settings.app_env,
            "engine_version": settings.engine_version,
            "auth_enabled": settings.auth_enabled,
            "database_configured": bool(settings.database_url),
        },
    )
    if not settings.auth_enabled and settings.is_production:  # pragma: no cover - guarded in config
        raise RuntimeError("refusing to start in production without DEMO_API_KEY")
    yield
    await dispose_engine()
    logger.info("shutdown")


def create_app() -> FastAPI:
    settings = get_settings()

    # Register redaction before anything else can log a provider URL containing a key.
    configure_logging(
        settings.log_level,
        secrets=(
            settings.etherscan_api_key,
            settings.trongrid_api_key,
            settings.bitquery_api_key,
            settings.demo_api_key,
            settings.database_url,
        ),
    )

    app = FastAPI(
        title="VASPTrace API",
        version=settings.engine_version,
        description=DESCRIPTION,
        openapi_url=f"{settings.api_prefix}/openapi.json",
        docs_url=f"{settings.api_prefix}/docs",
        redoc_url=None,
        lifespan=lifespan,
    )

    app.add_middleware(RequestContextMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=False,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Content-Type", "X-Api-Key", "X-Request-ID", "Idempotency-Key"],
        expose_headers=["X-Request-ID", "Retry-After"],
    )

    register_exception_handlers(app)
    app.include_router(api_router, prefix=settings.api_prefix)
    return app


app = create_app()
