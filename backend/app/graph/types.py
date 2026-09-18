"""Graph traversal result types.

Pure data containers produced by the traversal engine. Deliberately decoupled from the
ORM models (``app.database.models``) so the engine stays testable without a database.
The service layer maps these into ORM rows when persisting a trace.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal

from app.schemas.common import Chain, DataProvenance, Direction, NodeRole


@dataclass(frozen=True, slots=True)
class GraphNode:
    """One address discovered during traversal."""

    address: str  # canonical
    role: NodeRole
    hop_distance: int
    expanded: bool = False
    not_expanded_reason: str | None = None
    # Label hits populated by the label matcher (lightweight inline lookup)
    matched_vasp_name: str | None = None
    matched_vasp_slug: str | None = None
    matched_risk_entity_kind: str | None = None


@dataclass(frozen=True, slots=True)
class GraphEdge:
    """One transaction between two addresses, with full evidence."""

    from_address: str  # canonical
    to_address: str  # canonical
    tx_hash: str
    chain: Chain
    direction: Direction
    asset_symbol: str
    amount: Decimal
    block_timestamp: datetime
    hop_index: int  # the hop during which this edge was discovered
    dedup_key: str  # NormalizedTx.dedup_key, prevents duplicates


@dataclass(frozen=True, slots=True)
class CandidateVasp:
    """A VASP found at the end of a traversal path."""

    address: str
    vasp_name: str
    vasp_slug: str
    hop_distance: int
    path: tuple[str, ...]  # ordered addresses from subject to this VASP


@dataclass(slots=True)
class TraversalResult:
    """Complete output of one graph traversal run."""

    subject_address: str
    chain: Chain
    hop_depth: int
    direction: Direction
    provenance: DataProvenance

    nodes: dict[str, GraphNode] = field(default_factory=dict)  # keyed by canonical address
    edges: list[GraphEdge] = field(default_factory=list)
    candidates: list[CandidateVasp] = field(default_factory=list)
    paths: dict[str, tuple[str, ...]] = field(default_factory=dict)  # address → shortest path

    # Budget accounting
    nodes_expanded: int = 0
    api_calls: int = 0
    tx_analyzed: int = 0
    truncated: bool = False
    truncation_reason: str | None = None
    duration_ms: int | None = None

    @property
    def discovered_addresses(self) -> frozenset[str]:
        return frozenset(self.nodes.keys())

    @property
    def vasp_addresses(self) -> frozenset[str]:
        return frozenset(n.address for n in self.nodes.values() if n.role == NodeRole.VASP)

    @property
    def risk_addresses(self) -> frozenset[str]:
        return frozenset(n.address for n in self.nodes.values() if n.role == NodeRole.RISK_ENTITY)
