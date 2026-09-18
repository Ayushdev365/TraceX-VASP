"""The chain adapter contract.

Everything above the data layer imports only what is defined here. That is what lets
Bitcoin/Solana/Polygon land later without touching the traversal engine, the matcher or the
scorer (DPRD sec.7 chain-adapter architecture).

``NormalizedTx`` is the single cross-chain schema. Amounts are ``Decimal`` in human units
plus the exact integer base unit as a string — never floats, because an 18-decimal token
amount does not survive a float round-trip.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any, Protocol, runtime_checkable

from app.blockchain.addresses import AddressValidation
from app.schemas.common import Chain, DataProvenance, Direction, TxKind, TxStatus


@dataclass(frozen=True, slots=True)
class NormalizedTx:
    """One value movement, in the form the reasoning layer consumes."""

    chain: Chain
    tx_hash: str
    block_timestamp: datetime
    from_address: str  # canonical
    to_address: str  # canonical
    asset_symbol: str
    amount: Decimal  # human units
    amount_raw: str  # exact base units (wei, sun) as a decimal string
    decimals: int
    kind: TxKind
    status: TxStatus
    provenance: DataProvenance
    block_number: int | None = None
    asset_contract: str | None = None  # canonical, token transfers only
    log_index: int | None = None
    fee: Decimal | None = None

    @property
    def dedup_key(self) -> str:
        """Stable identity for an edge. A hash can move value between several pairs."""
        parts = (
            self.tx_hash,
            self.from_address,
            self.to_address,
            self.asset_symbol,
            self.kind.value,
            str(self.log_index) if self.log_index is not None else "-",
        )
        return "|".join(parts)


@dataclass(frozen=True, slots=True)
class Page:
    """One page of results, plus whether the provider has more.

    ``complete`` is the DPRD sec.17 data-completeness check: when a provider caps its result
    set, the caller must know the history was cut rather than assume it saw everything.
    """

    transactions: tuple[NormalizedTx, ...]
    next_cursor: str | None = None
    complete: bool = True
    truncation_reason: str | None = None
    provenance: DataProvenance = DataProvenance.LIVE_API
    api_calls: int = 0

    @property
    def has_more(self) -> bool:
        return self.next_cursor is not None


@dataclass(slots=True)
class FetchStats:
    """Per-trace provider accounting, so a trace can report what it actually cost."""

    api_calls: int = 0
    cache_hits: int = 0
    provenances: set[DataProvenance] = field(default_factory=set)

    def record(
        self, *, calls: int = 0, cached: bool = False, provenance: DataProvenance | None = None
    ) -> None:
        self.api_calls += calls
        if cached:
            self.cache_hits += 1
        if provenance is not None:
            self.provenances.add(provenance)

    def overall_provenance(self) -> DataProvenance:
        """Collapse the provenances seen into one honest label for the whole trace."""
        if not self.provenances:
            return DataProvenance.LIVE_API
        if len(self.provenances) == 1:
            return next(iter(self.provenances))
        # A mixture must never be reported as fully live (brief: never present mock or stale
        # data as a fresh blockchain read).
        return DataProvenance.MIXED


@runtime_checkable
class ChainAdapter(Protocol):
    """What every chain must implement. The five methods named in the build brief."""

    chain: Chain
    native_asset: str
    provenance: DataProvenance

    def validate_address(self, address: str) -> AddressValidation: ...

    async def get_wallet_transactions(
        self,
        address: str,
        *,
        direction: Direction = Direction.OUT,
        limit: int = 200,
        cursor: str | None = None,
    ) -> Page: ...

    async def get_token_transfers(
        self,
        address: str,
        *,
        direction: Direction = Direction.OUT,
        limit: int = 200,
        cursor: str | None = None,
    ) -> Page: ...

    async def get_transaction(self, tx_hash: str) -> NormalizedTx | None: ...

    def normalize_transaction(self, raw: dict[str, Any]) -> NormalizedTx | None: ...
