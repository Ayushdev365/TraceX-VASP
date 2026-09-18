"""v1 API router.

Routers are registered here as each phase lands, keeping ``main.py`` free of domain
imports. The endpoint inventory is in ``docs/API_CONTRACT.md``.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.api.v1 import addresses, labels, meta, vasps

api_router = APIRouter()
api_router.include_router(meta.router)
api_router.include_router(addresses.router)
api_router.include_router(vasps.router)
api_router.include_router(labels.router)

# Registered in later phases:
#   Phase 6  traces
#   Phase 10 cases, review
#   Phase 12 reports
#   Phase 13 disclosure
#   Phase 15 audit
