"""NetworkX-based transaction graph builder and multi-hop traversal engine.

The engine is the core of Phase 6. It consumes normalized blockchain transactions via a
``ChainAdapter`` and produces a ``TraversalResult`` containing the full graph, discovered
paths, and candidate VASP addresses.

Design constraints (DPRD sec.17, sec.28):

* **BFS-first** traversal: breadth-first ensures we find the *shortest* path to every
  address. DFS is used only for path reconstruction after BFS completes.
* **Deterministic**: for the same input the output is byte-identical across runs.
  Achieved by processing neighbours in sorted order and using stable dedup keys.
* **Budget-capped**: hop depth (1-6), node expansion count, API call count, and wall-clock
  time are all bounded so a trace can never run away.
* **Cycle-safe**: ``visited`` set prevents re-expansion; edges into already-visited nodes
  are still recorded (they are evidence).
* **Duplicate-safe**: ``NormalizedTx.dedup_key`` prevents the same transaction from
  appearing as two edges.

The engine does NOT:
* Touch the database (that is the service layer's job).
* Run ML models (Phase 9).
* Produce a score (Phase 8).

Label lookup is injected as a callable so the engine stays testable without a database.
"""

from __future__ import annotations

import logging
import time
from collections import deque
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

import networkx as nx

from app.blockchain.base import NormalizedTx, Page
from app.config import Settings, get_settings
from app.graph.types import (
    CandidateVasp,
    GraphEdge,
    GraphNode,
    TraversalResult,
)
from app.schemas.common import Chain, DataProvenance, Direction, NodeRole

logger = logging.getLogger(__name__)

# ─── label-lookup protocol ─────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class LabelHit:
    """Lightweight result from the label lookup."""

    vasp_name: str | None = None
    vasp_slug: str | None = None
    risk_entity_kind: str | None = None

    @property
    def is_vasp(self) -> bool:
        return self.vasp_name is not None

    @property
    def is_risk(self) -> bool:
        return self.risk_entity_kind is not None


#: Signature for the label-lookup callback: (chain, canonical_address) → LabelHit | None.
LabelLookupFn = Callable[[Chain, str], LabelHit | None]


def _no_labels(_chain: Chain, _address: str) -> LabelHit | None:
    """Default stub: no labels available. Used when tests don't care about labels."""
    return None


# ─── adapter fetch protocol ────────────────────────────────────────────────────


@runtime_checkable
class Fetcher(Protocol):
    """Subset of ChainAdapter the engine actually calls."""

    async def get_wallet_transactions(
        self,
        address: str,
        *,
        direction: Direction,
        limit: int,
    ) -> Page: ...

    async def get_token_transfers(
        self,
        address: str,
        *,
        direction: Direction,
        limit: int,
    ) -> Page: ...


# ─── budget tracker ─────────────────────────────────────────────────────────────


@dataclass(slots=True)
class _Budget:
    """Mutable state for resource-cap enforcement."""

    max_hops: int
    max_nodes: int
    max_api_calls: int
    max_txs_per_address: int
    wall_clock_deadline: float  # monotonic seconds
    fanout_terminal: int

    nodes_expanded: int = 0
    api_calls: int = 0
    tx_analyzed: int = 0

    exhausted_reason: str | None = None

    @classmethod
    def from_settings(
        cls,
        hop_depth: int,
        settings: Settings | None = None,
    ) -> _Budget:
        s = settings or get_settings()
        effective_hops = min(hop_depth, s.max_hop_depth)
        return cls(
            max_hops=effective_hops,
            max_nodes=s.max_nodes_expanded,
            max_api_calls=s.max_api_calls_per_trace,
            max_txs_per_address=s.max_txs_per_address,
            wall_clock_deadline=time.monotonic() + s.wall_clock_budget_s,
            fanout_terminal=s.fanout_terminal,
        )

    def can_expand(self) -> bool:
        if self.exhausted_reason is not None:
            return False
        if self.nodes_expanded >= self.max_nodes:
            self.exhausted_reason = f"node expansion limit reached ({self.max_nodes})"
            return False
        if self.api_calls >= self.max_api_calls:
            self.exhausted_reason = f"API call limit reached ({self.max_api_calls})"
            return False
        if time.monotonic() > self.wall_clock_deadline:
            self.exhausted_reason = "wall-clock budget exceeded"
            return False
        return True

    def record_expand(self, api_calls: int, tx_count: int) -> None:
        self.nodes_expanded += 1
        self.api_calls += api_calls
        self.tx_analyzed += tx_count


# ─── engine ─────────────────────────────────────────────────────────────────────


class TraversalEngine:
    """Build a transaction graph and traverse it using BFS.

    Usage::

        engine = TraversalEngine(adapter, chain)
        result = await engine.traverse(start_address, hop_depth=3)
    """

    def __init__(
        self,
        fetcher: Fetcher,
        chain: Chain,
        *,
        label_fn: LabelLookupFn | None = None,
        settings: Settings | None = None,
    ) -> None:
        self._fetcher = fetcher
        self._chain = chain
        self._label_fn = label_fn or _no_labels
        self._settings = settings

    async def traverse(
        self,
        start_address: str,
        *,
        hop_depth: int = 3,
        direction: Direction = Direction.OUT,
    ) -> TraversalResult:
        """Run BFS traversal from *start_address* up to *hop_depth* hops.

        Returns a fully populated ``TraversalResult``.
        """
        t0 = time.monotonic()
        budget = _Budget.from_settings(hop_depth, self._settings)
        effective_hops = budget.max_hops

        # Determine provenance from the fetcher
        provenance = getattr(self._fetcher, "provenance", DataProvenance.LIVE_API)

        result = TraversalResult(
            subject_address=start_address,
            chain=self._chain,
            hop_depth=effective_hops,
            direction=direction,
            provenance=provenance,
        )

        # Internal graph for path reconstruction
        G: nx.DiGraph = nx.DiGraph()

        # Tracking sets
        visited: set[str] = set()  # addresses we have expanded (fetched txs for)
        seen_edges: set[str] = set()  # dedup_key set for duplicate prevention

        # BFS queue: (address, hop_distance)
        queue: deque[tuple[str, int]] = deque()

        # Seed the subject
        subject_label = self._label_fn(self._chain, start_address)
        subject_role = self._classify_role(subject_label, is_subject=True)
        result.nodes[start_address] = GraphNode(
            address=start_address,
            role=subject_role,
            hop_distance=0,
            matched_vasp_name=subject_label.vasp_name if subject_label else None,
            matched_vasp_slug=subject_label.vasp_slug if subject_label else None,
            matched_risk_entity_kind=(subject_label.risk_entity_kind if subject_label else None),
        )
        G.add_node(start_address)
        result.paths[start_address] = (start_address,)
        queue.append((start_address, 0))

        # ── BFS loop ────────────────────────────────────────────────────────
        while queue:
            address, current_hop = queue.popleft()

            if address in visited:
                continue
            if current_hop >= effective_hops:
                # At max depth: record but don't expand
                continue
            if not budget.can_expand():
                result.truncated = True
                result.truncation_reason = budget.exhausted_reason
                break

            visited.add(address)

            # Fetch transactions
            transactions = await self._fetch_transactions(
                address, direction, budget.max_txs_per_address
            )
            api_calls_for_node = 2  # wallet + token transfers
            budget.record_expand(api_calls_for_node, len(transactions))

            # Check fanout
            counterparties = self._extract_counterparties(transactions, address, direction)
            if len(counterparties) > budget.fanout_terminal:
                # Too many counterparties — likely a contract or exchange hot wallet
                existing = result.nodes.get(address)
                if existing is not None:
                    result.nodes[address] = GraphNode(
                        address=existing.address,
                        role=NodeRole.CONTRACT,
                        hop_distance=existing.hop_distance,
                        expanded=False,
                        not_expanded_reason=f"fanout {len(counterparties)} exceeds terminal",
                        matched_vasp_name=existing.matched_vasp_name,
                        matched_vasp_slug=existing.matched_vasp_slug,
                        matched_risk_entity_kind=existing.matched_risk_entity_kind,
                    )
                continue

            # Mark node as expanded
            existing_node = result.nodes.get(address)
            if existing_node is not None and not existing_node.expanded:
                result.nodes[address] = GraphNode(
                    address=existing_node.address,
                    role=existing_node.role,
                    hop_distance=existing_node.hop_distance,
                    expanded=True,
                    matched_vasp_name=existing_node.matched_vasp_name,
                    matched_vasp_slug=existing_node.matched_vasp_slug,
                    matched_risk_entity_kind=existing_node.matched_risk_entity_kind,
                )

            # Process each transaction → edges and neighbour discovery
            next_hop = current_hop + 1
            for tx in sorted(transactions, key=lambda t: (t.to_address, t.tx_hash)):
                # Determine the neighbour address
                neighbour = tx.to_address if direction == Direction.OUT else tx.from_address

                if neighbour == address:
                    continue  # self-transfer

                # Deduplicate edges
                if tx.dedup_key in seen_edges:
                    continue
                seen_edges.add(tx.dedup_key)

                # Record the edge
                edge = GraphEdge(
                    from_address=tx.from_address,
                    to_address=tx.to_address,
                    tx_hash=tx.tx_hash,
                    chain=tx.chain,
                    direction=direction,
                    asset_symbol=tx.asset_symbol,
                    amount=tx.amount,
                    block_timestamp=tx.block_timestamp,
                    hop_index=next_hop,
                    dedup_key=tx.dedup_key,
                )
                result.edges.append(edge)

                # Add to networkx graph
                G.add_edge(
                    tx.from_address,
                    tx.to_address,
                    tx_hash=tx.tx_hash,
                    hop=next_hop,
                )

                # Discover the neighbour if not already known
                if neighbour not in result.nodes:
                    label = self._label_fn(self._chain, neighbour)
                    role = self._classify_role(label)
                    result.nodes[neighbour] = GraphNode(
                        address=neighbour,
                        role=role,
                        hop_distance=next_hop,
                        matched_vasp_name=label.vasp_name if label else None,
                        matched_vasp_slug=label.vasp_slug if label else None,
                        matched_risk_entity_kind=(label.risk_entity_kind if label else None),
                    )

                    # Compute shortest path
                    parent_path = result.paths.get(address, (address,))
                    result.paths[neighbour] = (*parent_path, neighbour)

                    # Enqueue for further expansion (unless it's at max depth)
                    if next_hop < effective_hops:
                        queue.append((neighbour, next_hop))

        # ── post-traversal: discover candidates ─────────────────────────────
        result.candidates = self._collect_candidates(result)

        # ── budget accounting ───────────────────────────────────────────────
        result.nodes_expanded = budget.nodes_expanded
        result.api_calls = budget.api_calls
        result.tx_analyzed = budget.tx_analyzed
        result.duration_ms = int((time.monotonic() - t0) * 1000)

        if budget.exhausted_reason and not result.truncated:
            result.truncated = True
            result.truncation_reason = budget.exhausted_reason

        logger.info(
            "traversal complete: %d nodes, %d edges, %d candidates, %d ms",
            len(result.nodes),
            len(result.edges),
            len(result.candidates),
            result.duration_ms,
        )

        return result

    # ─── private helpers ────────────────────────────────────────────────────

    async def _fetch_transactions(
        self,
        address: str,
        direction: Direction,
        limit: int,
    ) -> list[NormalizedTx]:
        """Fetch native + token transfers and merge them."""
        native_page = await self._fetcher.get_wallet_transactions(
            address, direction=direction, limit=limit
        )
        token_page = await self._fetcher.get_token_transfers(
            address, direction=direction, limit=limit
        )
        txs: list[NormalizedTx] = []
        txs.extend(native_page.transactions)
        txs.extend(token_page.transactions)
        return txs

    @staticmethod
    def _extract_counterparties(
        transactions: Sequence[NormalizedTx],
        address: str,
        direction: Direction,
    ) -> set[str]:
        """Unique counterparty addresses from a set of transactions."""
        result: set[str] = set()
        for tx in transactions:
            if direction == Direction.OUT:
                if tx.to_address != address:
                    result.add(tx.to_address)
            else:
                if tx.from_address != address:
                    result.add(tx.from_address)
        return result

    @staticmethod
    def _classify_role(label: LabelHit | None, *, is_subject: bool = False) -> NodeRole:
        if is_subject:
            return NodeRole.SUBJECT
        if label is not None:
            if label.is_risk:
                return NodeRole.RISK_ENTITY
            if label.is_vasp:
                return NodeRole.VASP
        return NodeRole.INTERMEDIATE

    @staticmethod
    def _collect_candidates(result: TraversalResult) -> list[CandidateVasp]:
        """Build sorted candidate list from VASP-labelled nodes."""
        candidates: list[CandidateVasp] = []
        for addr, node in sorted(result.nodes.items()):
            if node.role == NodeRole.VASP and node.matched_vasp_name is not None:
                path = result.paths.get(addr, (addr,))
                candidates.append(
                    CandidateVasp(
                        address=addr,
                        vasp_name=node.matched_vasp_name,
                        vasp_slug=node.matched_vasp_slug or "",
                        hop_distance=node.hop_distance,
                        path=path,
                    )
                )
        # Sort by hop_distance (closest first), then by address for stability.
        candidates.sort(key=lambda c: (c.hop_distance, c.address))
        return candidates
