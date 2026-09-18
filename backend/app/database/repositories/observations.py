"""Observation store — persisting normalized transactions, wallets and snapshots.

Every write here is idempotent. A trace re-runs the same provider queries as earlier traces
(shared intermediates are common), and re-running one must not duplicate rows or the
observed-activity counts that feed the fan-in/fan-out risk heuristics would inflate on every
repeat.

Idempotency is implemented as "select the existing natural keys, then insert only what is
new" rather than a dialect-specific ``ON CONFLICT``. One extra query per batch, in exchange
for identical behaviour on PostgreSQL and SQLite — worth it when the batch is at most a few
hundred rows and a dialect-specific path is a bug that would only appear in production.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select, tuple_, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.blockchain.base import NormalizedTx
from app.database.models import (
    ApiResponseCache,
    TokenTransfer,
    TraceSnapshotRef,
    Transaction,
    Wallet,
)
from app.schemas.common import Chain, TxKind


@dataclass(slots=True)
class PersistResult:
    """What a persist call actually changed, so a caller can report it honestly."""

    transactions_inserted: int = 0
    transactions_skipped: int = 0
    token_transfers_inserted: int = 0
    token_transfers_skipped: int = 0
    wallets_inserted: int = 0
    wallets_updated: int = 0

    @property
    def total_inserted(self) -> int:
        return self.transactions_inserted + self.token_transfers_inserted

    @property
    def total_skipped(self) -> int:
        return self.transactions_skipped + self.token_transfers_skipped


def _aware(value: datetime) -> datetime:
    """SQLite returns naive datetimes; compare and store as UTC either way."""
    return value if value.tzinfo else value.replace(tzinfo=UTC)


# ─── wallets ────────────────────────────────────────────────────────────────────


async def upsert_wallets(
    session: AsyncSession,
    chain: Chain,
    transactions: Sequence[NormalizedTx],
) -> tuple[int, int]:
    """Record every address seen, with first/last activity and an observed-tx count.

    Returns ``(inserted, updated)``. The counts are explicitly "as observed by our traces",
    not the chain totals — the field is named ``tx_count_observed`` for that reason, and it
    must never be presented as a wallet's true transaction count.
    """
    if not transactions:
        return 0, 0

    # Aggregate per address first, so one address touched twenty times is one UPDATE.
    seen: dict[str, dict[str, object]] = {}
    for tx in transactions:
        for address, display in (
            (tx.from_address, tx.from_address),
            (tx.to_address, tx.to_address),
        ):
            if not address:
                continue
            stamp = _aware(tx.block_timestamp)
            entry = seen.setdefault(
                address,
                {"display": display, "first": stamp, "last": stamp, "count": 0},
            )
            entry["count"] = int(entry["count"]) + 1  # type: ignore[call-overload]
            if stamp < entry["first"]:  # type: ignore[operator]
                entry["first"] = stamp
            if stamp > entry["last"]:  # type: ignore[operator]
                entry["last"] = stamp

    addresses = list(seen)
    existing = {
        row.address: row
        for row in (
            await session.execute(
                select(Wallet).where(Wallet.chain == chain.value, Wallet.address.in_(addresses))
            )
        )
        .scalars()
        .all()
    }

    inserted = updated = 0
    for address, entry in seen.items():
        first = entry["first"]
        last = entry["last"]
        count = int(entry["count"])  # type: ignore[call-overload]

        row = existing.get(address)
        if row is None:
            session.add(
                Wallet(
                    chain=chain.value,
                    address=address,
                    address_display=str(entry["display"]),
                    first_seen_at=first,
                    last_seen_at=last,
                    tx_count_observed=count,
                )
            )
            inserted += 1
            continue

        if row.first_seen_at is None or first < _aware(row.first_seen_at):  # type: ignore[operator]
            row.first_seen_at = first  # type: ignore[assignment]
        if row.last_seen_at is None or last > _aware(row.last_seen_at):  # type: ignore[operator]
            row.last_seen_at = last  # type: ignore[assignment]
        row.tx_count_observed = max(row.tx_count_observed or 0, count)
        updated += 1

    await session.flush()
    return inserted, updated


# ─── transactions ───────────────────────────────────────────────────────────────


def _native_key(tx: NormalizedTx) -> tuple[str, str, str, str, str, str]:
    """Matches ``uq_transactions_identity``."""
    return (
        tx.chain.value,
        tx.tx_hash,
        tx.from_address,
        tx.to_address,
        tx.asset_symbol,
        tx.kind.value,
    )


def _token_key(tx: NormalizedTx) -> tuple[str, str, int]:
    """Matches ``uq_token_transfers_identity``.

    A missing ``log_index`` becomes ``-1`` rather than NULL: NULLs never compare equal in a
    unique constraint, so a provider that omits the field would let the same transfer be
    inserted repeatedly.
    """
    return (tx.chain.value, tx.tx_hash, tx.log_index if tx.log_index is not None else -1)


async def persist_transactions(
    session: AsyncSession,
    transactions: Iterable[NormalizedTx],
    *,
    raw_ref: uuid.UUID | None = None,
) -> PersistResult:
    """Insert native/internal transfers and token transfers, skipping ones already stored."""
    result = PersistResult()

    native: list[NormalizedTx] = []
    tokens: list[NormalizedTx] = []
    for tx in transactions:
        (tokens if tx.kind is TxKind.TOKEN else native).append(tx)

    if native:
        # Dedup within the batch first: a merged native+internal page can repeat an edge.
        unique_native = {_native_key(tx): tx for tx in native}
        stored = set(
            (
                await session.execute(
                    select(
                        Transaction.chain,
                        Transaction.tx_hash,
                        Transaction.from_address,
                        Transaction.to_address,
                        Transaction.asset_symbol,
                        Transaction.kind,
                    ).where(
                        tuple_(
                            Transaction.chain,
                            Transaction.tx_hash,
                            Transaction.from_address,
                            Transaction.to_address,
                            Transaction.asset_symbol,
                            Transaction.kind,
                        ).in_(list(unique_native))
                    )
                )
            ).all()
        )
        for key, tx in unique_native.items():
            if key in stored:
                result.transactions_skipped += 1
                continue
            session.add(
                Transaction(
                    chain=tx.chain.value,
                    tx_hash=tx.tx_hash,
                    block_number=tx.block_number,
                    block_timestamp=_aware(tx.block_timestamp),
                    from_address=tx.from_address,
                    to_address=tx.to_address,
                    asset_symbol=tx.asset_symbol,
                    amount=tx.amount,
                    amount_raw=tx.amount_raw,
                    decimals=tx.decimals,
                    kind=tx.kind.value,
                    status=tx.status.value,
                    fee=tx.fee,
                    provenance=tx.provenance.value,
                    raw_ref=raw_ref,
                )
            )
            result.transactions_inserted += 1

    if tokens:
        unique_tokens = {_token_key(tx): tx for tx in tokens}
        stored_tokens = set(
            (
                await session.execute(
                    select(
                        TokenTransfer.chain, TokenTransfer.tx_hash, TokenTransfer.log_index
                    ).where(
                        tuple_(
                            TokenTransfer.chain, TokenTransfer.tx_hash, TokenTransfer.log_index
                        ).in_(list(unique_tokens))
                    )
                )
            ).all()
        )
        for token_key, tx in unique_tokens.items():
            if token_key in stored_tokens:
                result.token_transfers_skipped += 1
                continue
            session.add(
                TokenTransfer(
                    chain=tx.chain.value,
                    tx_hash=tx.tx_hash,
                    log_index=token_key[2],
                    block_number=tx.block_number,
                    block_timestamp=_aware(tx.block_timestamp),
                    from_address=tx.from_address,
                    to_address=tx.to_address,
                    asset_symbol=tx.asset_symbol,
                    asset_contract=tx.asset_contract or "",
                    amount=tx.amount,
                    amount_raw=tx.amount_raw,
                    decimals=tx.decimals,
                    status=tx.status.value,
                    fee=tx.fee,
                    provenance=tx.provenance.value,
                    raw_ref=raw_ref,
                )
            )
            result.token_transfers_inserted += 1

    await session.flush()
    return result


async def persist_page(
    session: AsyncSession,
    chain: Chain,
    transactions: Sequence[NormalizedTx],
    *,
    raw_ref: uuid.UUID | None = None,
) -> PersistResult:
    """Persist one adapter page: its transactions and the wallets they touch."""
    result = await persist_transactions(session, transactions, raw_ref=raw_ref)
    inserted, updated = await upsert_wallets(session, chain, transactions)
    result.wallets_inserted = inserted
    result.wallets_updated = updated
    return result


# ─── snapshots ──────────────────────────────────────────────────────────────────


async def pin_snapshots(
    session: AsyncSession,
    trace_id: uuid.UUID,
    cache_ids: Iterable[uuid.UUID],
) -> int:
    """Pin the provider responses that produced a trace, exempting them from eviction.

    This is what makes DPRD sec.15 reproducibility real: without it, the cache rows behind a
    report expire and the report can never be regenerated or explained again. Returns the
    number of newly pinned rows.
    """
    wanted = {cache_id for cache_id in cache_ids if cache_id is not None}
    if not wanted:
        return 0

    already = set(
        (
            await session.execute(
                select(TraceSnapshotRef.api_response_cache_id).where(
                    TraceSnapshotRef.trace_id == trace_id,
                    TraceSnapshotRef.api_response_cache_id.in_(list(wanted)),
                )
            )
        )
        .scalars()
        .all()
    )

    new = wanted - already
    for cache_id in new:
        session.add(TraceSnapshotRef(trace_id=trace_id, api_response_cache_id=cache_id))

    if new:
        # Snapshot rows must never expire, or the trace becomes unreproducible.
        await session.execute(
            update(ApiResponseCache)
            .where(ApiResponseCache.id.in_(list(new)))
            .values(is_snapshot=True, expires_at=None)
        )

    await session.flush()
    return len(new)


async def snapshot_ids_for_trace(session: AsyncSession, trace_id: uuid.UUID) -> list[uuid.UUID]:
    """Cache rows pinned to ``trace_id``, for the report's reproducibility block."""
    return list(
        (
            await session.execute(
                select(TraceSnapshotRef.api_response_cache_id).where(
                    TraceSnapshotRef.trace_id == trace_id
                )
            )
        )
        .scalars()
        .all()
    )


async def evict_expired_cache(session: AsyncSession, *, now: datetime | None = None) -> int:
    """Delete expired, unpinned cache rows. Returns the number removed."""
    from sqlalchemy import delete

    reference = now or datetime.now(UTC)
    rows = (
        await session.execute(
            select(ApiResponseCache.id, ApiResponseCache.expires_at).where(
                ApiResponseCache.is_snapshot.is_(False),
                ApiResponseCache.expires_at.is_not(None),
            )
        )
    ).all()
    stale = [row[0] for row in rows if row[1] is not None and _aware(row[1]) < reference]
    if not stale:
        return 0

    await session.execute(delete(ApiResponseCache).where(ApiResponseCache.id.in_(stale)))
    await session.flush()
    return len(stale)
