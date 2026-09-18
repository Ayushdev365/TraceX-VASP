"""Database-backed VASP label matcher service.

Bridges the PostgreSQL label repository to the synchronous graph traversal engine.
Because the engine discovers addresses dynamically but must remain synchronous on the
hot path (``LabelLookupFn``), this service acts as a ``Fetcher`` middleware: it intercepts
transaction queries, extracts counterparties, and batch-fetches their labels from the
database. The synchronous engine callback is then served purely from memory.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.blockchain.base import Page
from app.database.repositories.labels import AddressLabels, lookup_addresses
from app.graph.engine import Fetcher, LabelHit, TraversalEngine
from app.graph.types import TraversalResult
from app.schemas.common import ATTRIBUTABLE_TIERS, Chain, DataProvenance, Direction, LabelTier


class VaspLabelMatcher:
    """Preloads and caches labels for the graph traversal engine."""

    def __init__(self, session: AsyncSession, fetcher: Fetcher, chain: Chain) -> None:
        self._session = session
        self._fetcher = fetcher
        self._chain = chain
        self._cache: dict[str, AddressLabels] = {}

    @property
    def provenance(self) -> DataProvenance:
        """Passthrough so the engine knows the data source (e.g. MOCK_DEMO)."""
        return getattr(self._fetcher, "provenance", DataProvenance.LIVE_API)

    async def preload(self, addresses: list[str]) -> None:
        """Batch fetch labels for any addresses not already in the cache."""
        missing = [a for a in set(addresses) if a not in self._cache]
        if missing:
            labels = await lookup_addresses(self._session, self._chain, missing)
            self._cache.update(labels)
            # Mark addresses with no labels so we don't query them again
            for addr in missing:
                if addr not in self._cache:
                    self._cache[addr] = AddressLabels(
                        chain=self._chain,
                        address=addr,
                        vasp_addresses=(),
                        risk_entities=(),
                    )

    async def _preload_from_page(self, page: Page) -> None:
        """Extract all unique addresses from a transaction page and preload them."""
        addresses: set[str] = set()
        for tx in page.transactions:
            addresses.add(tx.from_address)
            addresses.add(tx.to_address)
        if addresses:
            await self.preload(list(addresses))

    # ─── Fetcher Protocol Implementation ──────────────────────────────────────

    async def get_wallet_transactions(
        self,
        address: str,
        *,
        direction: Direction,
        limit: int,
        **kwargs: Any,
    ) -> Page:
        page = await self._fetcher.get_wallet_transactions(
            address, direction=direction, limit=limit, **kwargs
        )
        await self._preload_from_page(page)
        return page

    async def get_token_transfers(
        self,
        address: str,
        *,
        direction: Direction,
        limit: int,
        **kwargs: Any,
    ) -> Page:
        page = await self._fetcher.get_token_transfers(
            address, direction=direction, limit=limit, **kwargs
        )
        await self._preload_from_page(page)
        return page

    # ─── Engine Callback ──────────────────────────────────────────────────────

    def lookup(self, chain: Chain, address: str) -> LabelHit | None:
        """Synchronous LabelLookupFn for the TraversalEngine."""
        if chain != self._chain:
            return None

        labels = self._cache.get(address)
        if not labels:
            return None

        # Find the first VASP label that supports attribution (i.e. not demo_unverified)
        valid_vasp = next(
            (va for va in labels.vasp_addresses if LabelTier(va.source_tier) in ATTRIBUTABLE_TIERS),
            None,
        )

        risk_kind = labels.risk_entities[0].entity_kind if labels.is_risk_entity else None

        if valid_vasp:
            vasp = valid_vasp.vasp
            return LabelHit(
                vasp_name=vasp.name,
                vasp_slug=vasp.slug,
                risk_entity_kind=risk_kind,
            )

        if risk_kind:
            return LabelHit(
                vasp_name=None,
                vasp_slug=None,
                risk_entity_kind=risk_kind,
            )

        return None

    # ─── Convenience Runner ───────────────────────────────────────────────────

    async def run_traversal(
        self,
        subject_address: str,
        hop_depth: int = 3,
        direction: Direction = Direction.OUT,
    ) -> TraversalResult:
        """Execute a graph traversal with database-backed label lookups."""
        # Preload the subject address so it gets labelled immediately at hop 0
        await self.preload([subject_address])

        engine = TraversalEngine(
            fetcher=self,  # we intercept fetches to batch-load labels
            chain=self._chain,
            label_fn=self.lookup,
        )
        return await engine.traverse(
            subject_address,
            hop_depth=hop_depth,
            direction=direction,
        )
