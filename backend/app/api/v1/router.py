"""v1 API router.

Routers are registered here as each phase lands, keeping ``main.py`` free of domain
imports. Phase 1 ships meta only; the endpoint inventory is in ``docs/API_CONTRACT.md``.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.api.v1 import meta

api_router = APIRouter()
api_router.include_router(meta.router)

# Registered in later phases:
#   Phase 2  vasps, labels
#   Phase 3  addresses
#   Phase 6  traces
#   Phase 10 cases, review
#   Phase 12 reports
#   Phase 13 disclosure
#   Phase 15 audit
