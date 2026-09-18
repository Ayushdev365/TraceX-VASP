"""FastAPI dependencies.

Auth is deliberately thin: the MVP validates a single demo key (DPRD sec.31 lists RBAC as
out of MVP scope). It is isolated here so swapping in SSO/RBAC at Pilot phase touches one
function rather than every endpoint.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends, Header
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.core.errors import Unauthorized
from app.database.session import session_scope


async def get_session() -> AsyncIterator[AsyncSession]:
    async for session in session_scope():
        yield session


DbSession = Annotated[AsyncSession, Depends(get_session)]
AppSettings = Annotated[Settings, Depends(get_settings)]


async def require_api_key(
    settings: AppSettings,
    x_api_key: Annotated[str | None, Header(alias="X-Api-Key")] = None,
) -> None:
    """Reject requests without the demo key — but only when one is configured.

    An unset ``DEMO_API_KEY`` leaves the API open, which is acceptable for local
    development and is reported honestly by ``/health`` as ``auth: not_configured``.
    Production cannot start without the key (see ``Settings._check_consistency``).
    """
    if not settings.auth_enabled:
        return
    if x_api_key != settings.demo_api_key:
        raise Unauthorized()


RequireApiKey = Depends(require_api_key)
