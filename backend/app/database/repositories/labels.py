"""Queries against the labelled datasets.

The hot path here is :func:`lookup_addresses` — the traversal engine calls it once per hop
with every address discovered at that hop, so it is written as a single batched query rather
than one query per address. At six hops with a few hundred nodes, per-address queries would
dominate the trace's latency budget.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database.models import (
    LabelDatasetVersion,
    RiskEntity,
    Vasp,
    VaspAddress,
)
from app.schemas.common import ATTRIBUTABLE_TIERS, Chain, LabelTier


@dataclass(frozen=True, slots=True)
class AddressLabels:
    """Everything the datasets know about one address."""

    chain: Chain
    address: str
    vasp_addresses: tuple[VaspAddress, ...]
    risk_entities: tuple[RiskEntity, ...]

    @property
    def is_vasp(self) -> bool:
        return bool(self.vasp_addresses)

    @property
    def is_risk_entity(self) -> bool:
        return bool(self.risk_entities)

    @property
    def has_conflicting_labels(self) -> bool:
        """True when sources disagree about which VASP owns this address (DPRD sec.21)."""
        return len({row.vasp_id for row in self.vasp_addresses}) > 1

    @property
    def can_support_attribution(self) -> bool:
        """True when at least one label is from a tier stronger than ``demo_unverified``."""
        return any(LabelTier(row.source_tier) in ATTRIBUTABLE_TIERS for row in self.vasp_addresses)


def label_age_days(value: datetime | None, *, now: datetime | None = None) -> int:
    if value is None:
        return 0
    reference = now or datetime.now(UTC)
    stamp = value if value.tzinfo else value.replace(tzinfo=UTC)
    return max(0, (reference - stamp).days)


def _active_vasp_addresses() -> Select[tuple[VaspAddress]]:
    return select(VaspAddress).where(VaspAddress.is_active.is_(True))


async def lookup_addresses(
    session: AsyncSession,
    chain: Chain,
    addresses: list[str],
) -> dict[str, AddressLabels]:
    """Batched label lookup. Keys are the canonical addresses that matched something.

    Addresses must already be canonical — see ``app/blockchain/addresses.py``. Passing a
    checksummed or hex-form address here is the DPRD sec.17 format-mismatch failure mode and
    would silently return nothing.
    """
    if not addresses:
        return {}

    unique = list(dict.fromkeys(addresses))

    vasp_rows = (
        (
            await session.execute(
                _active_vasp_addresses()
                .where(VaspAddress.chain == chain.value, VaspAddress.address.in_(unique))
                .options(selectinload(VaspAddress.vasp))
            )
        )
        .scalars()
        .all()
    )
    risk_rows = (
        (
            await session.execute(
                select(RiskEntity).where(
                    RiskEntity.is_active.is_(True),
                    RiskEntity.chain == chain.value,
                    RiskEntity.address.in_(unique),
                )
            )
        )
        .scalars()
        .all()
    )

    grouped_vasp: dict[str, list[VaspAddress]] = defaultdict(list)
    for row in vasp_rows:
        grouped_vasp[row.address].append(row)
    grouped_risk: dict[str, list[RiskEntity]] = defaultdict(list)
    for risk_row in risk_rows:
        grouped_risk[risk_row.address].append(risk_row)

    return {
        address: AddressLabels(
            chain=chain,
            address=address,
            vasp_addresses=tuple(grouped_vasp.get(address, ())),
            risk_entities=tuple(grouped_risk.get(address, ())),
        )
        for address in set(grouped_vasp) | set(grouped_risk)
    }


async def lookup_address(session: AsyncSession, chain: Chain, address: str) -> AddressLabels:
    """Single-address lookup. Returns an empty result rather than None when unlabelled."""
    found = await lookup_addresses(session, chain, [address])
    return found.get(
        address,
        AddressLabels(chain=chain, address=address, vasp_addresses=(), risk_entities=()),
    )


async def list_vasps(
    session: AsyncSession,
    *,
    chain: Chain | None = None,
    query: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> tuple[list[tuple[Vasp, int, list[str]]], int]:
    """VASPs with their active address counts and the chains they are known on."""
    statement = select(Vasp).options(selectinload(Vasp.addresses))
    if query:
        pattern = f"%{query.lower()}%"
        statement = statement.where(
            func.lower(Vasp.name).like(pattern) | func.lower(Vasp.slug).like(pattern)
        )

    vasps = (await session.execute(statement.order_by(Vasp.name))).scalars().all()

    enriched: list[tuple[Vasp, int, list[str]]] = []
    for vasp in vasps:
        active = [a for a in vasp.addresses if a.is_active]
        if chain is not None:
            active = [a for a in active if a.chain == chain.value]
            if not active:
                continue
        enriched.append((vasp, len(active), sorted({a.chain for a in active})))

    return enriched[offset : offset + limit], len(enriched)


async def get_vasp_by_slug(session: AsyncSession, slug: str) -> Vasp | None:
    return (
        await session.execute(
            select(Vasp).where(Vasp.slug == slug.lower()).options(selectinload(Vasp.addresses))
        )
    ).scalar_one_or_none()


async def search_addresses(
    session: AsyncSession, *, chain: Chain | None, fragment: str, limit: int = 50
) -> list[VaspAddress]:
    """Substring search over labelled addresses, for the admin/directory view."""
    statement = _active_vasp_addresses().options(selectinload(VaspAddress.vasp))
    if chain is not None:
        statement = statement.where(VaspAddress.chain == chain.value)
    statement = statement.where(func.lower(VaspAddress.address).like(f"%{fragment.lower()}%"))
    return list((await session.execute(statement.limit(limit))).scalars().all())


@dataclass(frozen=True, slots=True)
class ChainCoverageStats:
    vasp_count: int
    vasp_address_count: int
    risk_entity_count: int


async def chain_coverage(session: AsyncSession) -> dict[str, ChainCoverageStats]:
    """Per-chain label counts, used by ``/meta/chains`` and by every trace's coverage notice."""
    vasp_rows = (
        await session.execute(
            select(
                VaspAddress.chain,
                func.count(VaspAddress.id),
                func.count(func.distinct(VaspAddress.vasp_id)),
            )
            .where(VaspAddress.is_active.is_(True))
            .group_by(VaspAddress.chain)
        )
    ).all()
    risk_rows = (
        await session.execute(
            select(RiskEntity.chain, func.count(RiskEntity.id))
            .where(RiskEntity.is_active.is_(True))
            .group_by(RiskEntity.chain)
        )
    ).all()

    risk_by_chain: dict[str, int] = {row[0]: row[1] for row in risk_rows}
    coverage = {
        chain: ChainCoverageStats(
            vasp_count=vasp_count,
            vasp_address_count=address_count,
            risk_entity_count=risk_by_chain.get(chain, 0),
        )
        for chain, address_count, vasp_count in vasp_rows
    }
    for chain, count in risk_by_chain.items():
        if chain not in coverage:
            coverage[chain] = ChainCoverageStats(0, 0, count)
    return coverage


async def latest_dataset_version(session: AsyncSession) -> LabelDatasetVersion | None:
    """The most recent import. Pinned to every new trace for reproducibility."""
    return (
        await session.execute(
            select(LabelDatasetVersion).order_by(LabelDatasetVersion.imported_at.desc()).limit(1)
        )
    ).scalar_one_or_none()


async def list_dataset_versions(
    session: AsyncSession, *, limit: int = 20
) -> list[LabelDatasetVersion]:
    return list(
        (
            await session.execute(
                select(LabelDatasetVersion)
                .order_by(LabelDatasetVersion.imported_at.desc())
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )


async def get_dataset_version(
    session: AsyncSession, version_id: uuid.UUID
) -> LabelDatasetVersion | None:
    return await session.get(LabelDatasetVersion, version_id)
