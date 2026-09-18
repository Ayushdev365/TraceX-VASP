"""Shared provider HTTP layer: rate limiting, retries, timeouts, caching.

One client serves every adapter so the failure behaviour is identical across chains — the
DPRD sec.48 task 34 requirement to define API-failure handling before relying on a provider in
a live demo.

Three properties matter:

1. **Keys never leak.** The API key is added at request time and stripped before anything is
   cached or logged. ``request_params`` in the cache table is the sanitised copy.
2. **Rate limits are respected proactively.** Free tiers are ~5 req/s; a token bucket paces
   requests rather than waiting to be rejected. A 429 still retries with backoff, then
   surfaces as a clean ``UpstreamRateLimited`` instead of a stack trace.
3. **Cached reads are labelled.** A cache hit returns ``DataProvenance.CACHED``, so a demo
   served from a warm cache is never reported as a fresh live pull.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, ClassVar

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.errors import UpstreamProviderError, UpstreamRateLimited
from app.core.logging import get_logger
from app.database.models import ApiResponseCache
from app.schemas.common import Chain, DataProvenance

logger = get_logger(__name__)

#: Query parameter names that carry credentials. Stripped before caching or logging.
SECRET_PARAMS = frozenset({"apikey", "api_key", "apiKey", "key", "access_token", "auth"})

CONNECT_TIMEOUT_S = 5.0
READ_TIMEOUT_S = 20.0
MAX_ATTEMPTS = 3
BACKOFF_BASE_S = 0.5


def _as_utc(value: datetime) -> datetime:
    """Treat a naive timestamp as UTC.

    SQLite has no timezone type, so the dev fallback reads back naive datetimes. Comparing
    one of those to an aware ``now()`` raises, which would disable caching entirely on the
    fallback — and only on the fallback, making it an easy bug to miss.
    """
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def sanitize_params(params: dict[str, Any]) -> dict[str, Any]:
    """Copy of ``params`` with every credential removed."""
    return {k: v for k, v in params.items() if k not in SECRET_PARAMS}


def cache_key(provider: str, endpoint: str, params: dict[str, Any]) -> str:
    """Deterministic key over the sanitised parameters, sorted for stability."""
    payload = json.dumps(
        {"provider": provider, "endpoint": endpoint, "params": sanitize_params(params)},
        sort_keys=True,
        default=str,
    )
    return hashlib.sha256(payload.encode()).hexdigest()


class TokenBucket:
    """Simple async rate limiter, one per provider."""

    def __init__(self, rate_per_second: float, burst: int = 1) -> None:
        self._rate = rate_per_second
        self._capacity = max(1.0, float(burst))
        self._tokens = self._capacity
        self._updated = time.monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        async with self._lock:
            now = time.monotonic()
            self._tokens = min(self._capacity, self._tokens + (now - self._updated) * self._rate)
            self._updated = now
            if self._tokens < 1.0:
                wait = (1.0 - self._tokens) / self._rate
                await asyncio.sleep(wait)
                self._tokens = 0.0
                self._updated = time.monotonic()
            else:
                self._tokens -= 1.0


@dataclass(slots=True)
class ProviderResponse:
    """One provider reply, with where it came from."""

    body: dict[str, Any]
    http_status: int
    provenance: DataProvenance
    api_calls: int
    cache_id: Any = None


class ProviderClient:
    """Rate-limited, retrying, caching HTTP client for one provider."""

    #: Shared buckets keyed by provider name, so two adapters on the same provider share quota.
    _buckets: ClassVar[dict[str, TokenBucket]] = {}

    def __init__(
        self,
        provider: str,
        base_url: str,
        *,
        chain: Chain,
        rate_per_second: float = 4.0,
        session: AsyncSession | None = None,
    ) -> None:
        self.provider = provider
        self.base_url = base_url.rstrip("/")
        self.chain = chain
        self.session = session
        self._bucket = ProviderClient._buckets.setdefault(
            provider, TokenBucket(rate_per_second, burst=2)
        )

    # ─── cache ──────────────────────────────────────────────────────────────

    async def _lookup(self, key: str) -> ApiResponseCache | None:
        if self.session is None:
            return None
        return (
            await self.session.execute(
                select(ApiResponseCache).where(ApiResponseCache.cache_key == key)
            )
        ).scalar_one_or_none()

    async def _read_cache(self, key: str) -> ApiResponseCache | None:
        row = await self._lookup(key)
        if row is None:
            return None
        if row.expires_at is not None and _as_utc(row.expires_at) < datetime.now(UTC):
            return None
        return row

    async def _write_cache(
        self, key: str, endpoint: str, params: dict[str, Any], body: dict[str, Any], status: int
    ) -> Any:
        """Insert or refresh the cache row for ``key``.

        Upsert rather than insert: a forced refresh re-reads a key that already exists, and
        inserting again would violate the unique constraint mid-trace.
        """
        if self.session is None:
            return None

        ttl = get_settings().chain_cache_ttl_s
        now = datetime.now(UTC)
        expires_at = now + timedelta(seconds=ttl) if ttl else None

        existing = await self._lookup(key)
        if existing is not None:
            existing.response_body = body
            existing.http_status = status
            existing.fetched_at = now
            # A row pinned as a trace snapshot keeps its non-expiring status.
            if not existing.is_snapshot:
                existing.expires_at = expires_at
            await self.session.flush()
            return existing.id

        row = ApiResponseCache(
            cache_key=key,
            chain=self.chain.value,
            provider=self.provider,
            endpoint=endpoint,
            request_params=sanitize_params(params),  # never store the key
            response_body=body,
            http_status=status,
            fetched_at=now,
            expires_at=expires_at,
        )
        self.session.add(row)
        await self.session.flush()
        return row.id

    # ─── request ────────────────────────────────────────────────────────────

    async def get_json(
        self,
        endpoint: str,
        params: dict[str, Any],
        *,
        secret_params: dict[str, Any] | None = None,
        force_refresh: bool = False,
    ) -> ProviderResponse:
        """GET ``endpoint``, returning a parsed body.

        ``params`` are cacheable and loggable; ``secret_params`` are sent but never stored.
        """
        key = cache_key(self.provider, endpoint, params)

        if not force_refresh:
            cached = await self._read_cache(key)
            if cached is not None:
                logger.info("provider_cache_hit", extra={"provider": self.provider})
                return ProviderResponse(
                    body=cached.response_body,
                    http_status=cached.http_status,
                    provenance=DataProvenance.CACHED,
                    api_calls=0,
                    cache_id=cached.id,
                )

        url = f"{self.base_url}/{endpoint.lstrip('/')}" if endpoint else self.base_url
        sent = {**params, **(secret_params or {})}
        timeout = httpx.Timeout(READ_TIMEOUT_S, connect=CONNECT_TIMEOUT_S)
        last_error: Exception | None = None
        calls = 0

        for attempt in range(1, MAX_ATTEMPTS + 1):
            await self._bucket.acquire()
            calls += 1
            try:
                async with httpx.AsyncClient(timeout=timeout) as client:
                    response = await client.get(url, params=sent)
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                last_error = exc
                logger.warning(
                    "provider_request_failed",
                    extra={
                        "provider": self.provider,
                        "attempt": attempt,
                        "error_type": type(exc).__name__,
                    },
                )
                if attempt < MAX_ATTEMPTS:
                    await asyncio.sleep(BACKOFF_BASE_S * 2 ** (attempt - 1))
                    continue
                raise UpstreamProviderError(
                    f"The {self.chain.value} data provider did not respond.",
                    details={"provider": self.provider, "attempts": attempt},
                ) from exc

            if response.status_code == 429:
                retry_after = float(response.headers.get("Retry-After", BACKOFF_BASE_S * attempt))
                if attempt < MAX_ATTEMPTS:
                    await asyncio.sleep(min(retry_after, 5.0))
                    continue
                raise UpstreamRateLimited(
                    f"The {self.chain.value} data provider's rate limit was reached. "
                    f"Please retry shortly.",
                    details={"provider": self.provider, "retry_after_s": int(retry_after)},
                )

            if response.status_code >= 500:
                if attempt < MAX_ATTEMPTS:
                    await asyncio.sleep(BACKOFF_BASE_S * 2 ** (attempt - 1))
                    continue
                raise UpstreamProviderError(
                    f"The {self.chain.value} data provider returned a server error.",
                    details={"provider": self.provider, "http_status": response.status_code},
                )

            if response.status_code >= 400:
                # Client errors are not retried; the upstream body is deliberately discarded
                # in case it echoes the request (and therefore the key).
                raise UpstreamProviderError(
                    f"The {self.chain.value} data provider rejected the request.",
                    details={"provider": self.provider, "http_status": response.status_code},
                )

            try:
                body = response.json()
            except ValueError as exc:
                raise UpstreamProviderError(
                    f"The {self.chain.value} data provider returned an unreadable response.",
                    details={"provider": self.provider},
                ) from exc

            if not isinstance(body, dict):
                body = {"result": body}

            cache_id = await self._write_cache(key, endpoint, params, body, response.status_code)
            return ProviderResponse(
                body=body,
                http_status=response.status_code,
                provenance=DataProvenance.LIVE_API,
                api_calls=calls,
                cache_id=cache_id,
            )

        raise UpstreamProviderError(
            f"The {self.chain.value} data provider could not be reached.",
            details={"provider": self.provider},
        ) from last_error
