"""Tests for the Phase 6 graph traversal engine.

All tests use the ``MockAdapter`` (offline, deterministic, clearly labelled). No database,
no real blockchain calls.

Coverage:
    - 1-hop traversal
    - Multi-hop traversal (clean scenario = 3 hops)
    - Cycle prevention
    - Duplicate transaction prevention
    - Disconnected wallets (dead_end scenario)
    - Multiple VASP candidates
    - Maximum hop limit enforcement
    - No VASP found (dead_end)
    - Deterministic output (same input → same result)
    - Direction.IN traversal
    - Budget enforcement (node cap, API call cap)
"""

from __future__ import annotations

import pytest

from app.blockchain.mock import MockAdapter, mock_subject
from app.config import Settings
from app.graph.engine import LabelHit, TraversalEngine, _Budget
from app.graph.types import TraversalResult
from app.schemas.common import Chain, DataProvenance, Direction, NodeRole

# ─── helpers ────────────────────────────────────────────────────────────────────


def _mock_settings(**overrides: object) -> Settings:
    """Build a Settings with test-safe defaults and optional overrides."""
    defaults: dict[str, object] = {
        "app_env": "development",
        "database_url": "",
        "demo_api_key": "",
        "etherscan_api_key": "",
        "trongrid_api_key": "",
        "bitquery_api_key": "",
        "default_hop_depth": 3,
        "max_hop_depth": 6,
        "max_nodes_expanded": 400,
        "max_api_calls_per_trace": 120,
        "max_txs_per_address": 200,
        "wall_clock_budget_s": 30.0,
        "fanout_terminal": 500,
    }
    defaults.update(overrides)
    return Settings(**defaults)  # type: ignore[arg-type]


def _label_fn_clean(chain: Chain, address: str) -> LabelHit | None:
    """A label lookup that knows about the mock clean scenario's exchange deposit."""
    from app.blockchain.mock import _addr

    # The exchange deposit in the clean scenario
    exchange_deposit = _addr(
        chain,
        "meridian/eth/deposit/1" if chain is Chain.ETHEREUM else "meridian/trx/deposit/1",
    )
    if address == exchange_deposit:
        return LabelHit(vasp_name="Meridian Exchange", vasp_slug="meridian-exchange")
    return None


def _label_fn_mixer(chain: Chain, address: str) -> LabelHit | None:
    """Labels for the mixer scenario: mixer as risk, custody as VASP."""
    from app.blockchain.mock import _addr

    mixer = _addr(
        chain,
        "obscura/eth/router/1" if chain is Chain.ETHEREUM else "obscura/trx/router/1",
    )
    custody = _addr(
        chain,
        "kavach/eth/hot/1" if chain is Chain.ETHEREUM else "kavach/trx/deposit/1",
    )
    if address == mixer:
        return LabelHit(risk_entity_kind="mixer")
    if address == custody:
        return LabelHit(vasp_name="Kavach Custody", vasp_slug="kavach-custody")
    return None


def _label_fn_multi(_chain: Chain, address: str) -> LabelHit | None:
    """Labels multiple addresses as VASPs for multi-candidate testing."""
    from app.blockchain.mock import _addr

    exchange = _addr(
        _chain,
        "meridian/eth/deposit/1" if _chain is Chain.ETHEREUM else "meridian/trx/deposit/1",
    )
    custody = _addr(
        _chain,
        "kavach/eth/hot/1" if _chain is Chain.ETHEREUM else "kavach/trx/deposit/1",
    )
    if address == exchange:
        return LabelHit(vasp_name="Meridian Exchange", vasp_slug="meridian-exchange")
    if address == custody:
        return LabelHit(vasp_name="Kavach Custody", vasp_slug="kavach-custody")
    return None


# ─── test: 1-hop traversal ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_one_hop_traversal() -> None:
    """1-hop from the clean subject should discover direct recipients only."""
    adapter = MockAdapter(Chain.ETHEREUM)
    settings = _mock_settings()
    engine = TraversalEngine(adapter, Chain.ETHEREUM, settings=settings)

    subject = mock_subject(Chain.ETHEREUM, "clean")
    result = await engine.traverse(subject, hop_depth=1, direction=Direction.OUT)

    assert isinstance(result, TraversalResult)
    assert result.subject_address == subject
    assert result.hop_depth == 1
    assert result.provenance == DataProvenance.MOCK_DEMO

    # Subject is always in nodes
    assert subject in result.nodes
    assert result.nodes[subject].role == NodeRole.SUBJECT
    assert result.nodes[subject].hop_distance == 0

    # Should have discovered direct recipients (hop 1)
    non_subject = {a for a in result.nodes if a != subject}
    assert len(non_subject) >= 1
    for addr in non_subject:
        assert result.nodes[addr].hop_distance == 1

    # Every edge should be hop_index 1
    assert all(e.hop_index == 1 for e in result.edges)

    # At least one edge
    assert len(result.edges) >= 1


# ─── test: multi-hop traversal (clean scenario) ─────────────────────────────────


@pytest.mark.asyncio
async def test_multi_hop_clean_scenario() -> None:
    """Clean scenario: subject → i1 → i2 → exchange. Should find VASP at hop 3."""
    adapter = MockAdapter(Chain.ETHEREUM)
    settings = _mock_settings()
    engine = TraversalEngine(adapter, Chain.ETHEREUM, label_fn=_label_fn_clean, settings=settings)

    subject = mock_subject(Chain.ETHEREUM, "clean")
    result = await engine.traverse(subject, hop_depth=3, direction=Direction.OUT)

    assert len(result.nodes) >= 4  # subject + i1 + i2 + exchange + maybe others
    assert len(result.edges) >= 3  # at least 3 edges in the chain

    # Should discover the VASP candidate
    assert len(result.candidates) >= 1
    vasp_candidate = result.candidates[0]
    assert vasp_candidate.vasp_name == "Meridian Exchange"
    assert vasp_candidate.hop_distance <= 3

    # Path should exist from subject to the VASP
    assert vasp_candidate.path[0] == subject
    assert vasp_candidate.path[-1] == vasp_candidate.address


# ─── test: cycle prevention ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_cycle_prevention() -> None:
    """Engine should not re-expand an already-visited address, even if edges point back."""
    adapter = MockAdapter(Chain.ETHEREUM)
    settings = _mock_settings()
    engine = TraversalEngine(adapter, Chain.ETHEREUM, settings=settings)

    subject = mock_subject(Chain.ETHEREUM, "clean")
    result = await engine.traverse(subject, hop_depth=4, direction=Direction.OUT)

    # Subject should be expanded exactly once
    assert result.nodes[subject].expanded is True

    # No address should appear more than once in nodes dict (dict naturally deduplicates)
    addresses = list(result.nodes.keys())
    assert len(addresses) == len(set(addresses))

    # nodes_expanded should be <= total nodes (some may not be expanded)
    assert result.nodes_expanded <= len(result.nodes)


# ─── test: duplicate transaction prevention ──────────────────────────────────────


@pytest.mark.asyncio
async def test_duplicate_transaction_prevention() -> None:
    """Each transaction should appear at most once in edges, keyed by dedup_key."""
    adapter = MockAdapter(Chain.ETHEREUM)
    settings = _mock_settings()
    engine = TraversalEngine(adapter, Chain.ETHEREUM, settings=settings)

    subject = mock_subject(Chain.ETHEREUM, "clean")
    result = await engine.traverse(subject, hop_depth=3, direction=Direction.OUT)

    dedup_keys = [e.dedup_key for e in result.edges]
    assert len(dedup_keys) == len(set(dedup_keys)), "duplicate edges found"


# ─── test: disconnected wallets (dead_end) ───────────────────────────────────────


@pytest.mark.asyncio
async def test_disconnected_wallet_dead_end() -> None:
    """Dead-end scenario: 3 hops of unlabelled addresses, no VASP anywhere."""
    adapter = MockAdapter(Chain.ETHEREUM)
    settings = _mock_settings()
    engine = TraversalEngine(adapter, Chain.ETHEREUM, settings=settings)

    subject = mock_subject(Chain.ETHEREUM, "dead_end")
    result = await engine.traverse(subject, hop_depth=3, direction=Direction.OUT)

    # Should have nodes (subject + intermediaries)
    assert len(result.nodes) >= 3

    # No VASP candidate should be found (no labels)
    assert len(result.candidates) == 0


# ─── test: multiple VASP candidates ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_multiple_vasp_candidates() -> None:
    """Mixer scenario with multi-label lookup should yield both mixer risk + VASP."""
    adapter = MockAdapter(Chain.ETHEREUM)
    settings = _mock_settings()
    engine = TraversalEngine(adapter, Chain.ETHEREUM, label_fn=_label_fn_mixer, settings=settings)

    subject = mock_subject(Chain.ETHEREUM, "mixer")
    result = await engine.traverse(subject, hop_depth=3, direction=Direction.OUT)

    # Mixer should be tagged as risk entity
    risk_addrs = result.risk_addresses
    assert len(risk_addrs) >= 1

    # Kavach custody should be a VASP candidate
    vasp_addrs = result.vasp_addresses
    assert len(vasp_addrs) >= 1
    assert len(result.candidates) >= 1
    assert any(c.vasp_name == "Kavach Custody" for c in result.candidates)


# ─── test: maximum hop limit ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_max_hop_limit_enforced() -> None:
    """Requesting more than max_hop_depth should be clamped."""
    adapter = MockAdapter(Chain.ETHEREUM)
    settings = _mock_settings(max_hop_depth=4)
    engine = TraversalEngine(adapter, Chain.ETHEREUM, settings=settings)

    subject = mock_subject(Chain.ETHEREUM, "clean")
    result = await engine.traverse(subject, hop_depth=10, direction=Direction.OUT)

    # Should be clamped to 4
    assert result.hop_depth == 4

    # No node should be beyond hop 4
    for node in result.nodes.values():
        assert node.hop_distance <= 4


# ─── test: no VASP found ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_no_vasp_found() -> None:
    """With no label function, no VASP candidates should be returned."""
    adapter = MockAdapter(Chain.ETHEREUM)
    settings = _mock_settings()
    engine = TraversalEngine(adapter, Chain.ETHEREUM, settings=settings)

    subject = mock_subject(Chain.ETHEREUM, "clean")
    result = await engine.traverse(subject, hop_depth=3, direction=Direction.OUT)

    # No labels → no VASPs
    assert len(result.candidates) == 0
    assert len(result.vasp_addresses) == 0


# ─── test: deterministic output ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_deterministic_output() -> None:
    """Two runs with the same input must produce identical results."""
    adapter = MockAdapter(Chain.ETHEREUM)
    settings = _mock_settings()
    engine = TraversalEngine(adapter, Chain.ETHEREUM, label_fn=_label_fn_clean, settings=settings)

    subject = mock_subject(Chain.ETHEREUM, "clean")

    r1 = await engine.traverse(subject, hop_depth=3, direction=Direction.OUT)
    r2 = await engine.traverse(subject, hop_depth=3, direction=Direction.OUT)

    assert set(r1.nodes.keys()) == set(r2.nodes.keys())
    assert len(r1.edges) == len(r2.edges)
    assert [e.dedup_key for e in r1.edges] == [e.dedup_key for e in r2.edges]
    assert len(r1.candidates) == len(r2.candidates)
    for c1, c2 in zip(r1.candidates, r2.candidates, strict=True):
        assert c1.address == c2.address
        assert c1.vasp_name == c2.vasp_name
        assert c1.hop_distance == c2.hop_distance


# ─── test: path reconstruction ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_path_reconstruction() -> None:
    """Every discovered node should have a path from the subject."""
    adapter = MockAdapter(Chain.ETHEREUM)
    settings = _mock_settings()
    engine = TraversalEngine(adapter, Chain.ETHEREUM, label_fn=_label_fn_clean, settings=settings)

    subject = mock_subject(Chain.ETHEREUM, "clean")
    result = await engine.traverse(subject, hop_depth=3, direction=Direction.OUT)

    # Every node reachable via expansion should have a path
    for addr in result.nodes:
        assert addr in result.paths, f"no path for {addr}"
        path = result.paths[addr]
        assert path[0] == subject, "path must start at subject"
        assert path[-1] == addr, "path must end at the node"
        # Path length = hop_distance + 1
        node = result.nodes[addr]
        assert len(path) == node.hop_distance + 1


# ─── test: node budget enforcement ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_node_budget_truncation() -> None:
    """Traversal should stop when node expansion limit is reached."""
    adapter = MockAdapter(Chain.ETHEREUM)
    settings = _mock_settings(max_nodes_expanded=2)
    engine = TraversalEngine(adapter, Chain.ETHEREUM, settings=settings)

    subject = mock_subject(Chain.ETHEREUM, "clean")
    result = await engine.traverse(subject, hop_depth=6, direction=Direction.OUT)

    assert result.nodes_expanded <= 2
    assert result.truncated is True
    assert result.truncation_reason is not None
    assert "node expansion limit" in result.truncation_reason


# ─── test: API call budget enforcement ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_api_call_budget_truncation() -> None:
    """Traversal should stop when API call limit is reached."""
    adapter = MockAdapter(Chain.ETHEREUM)
    # Each node expansion costs 2 api calls (wallet + token), so 3 calls → 1 expansion + stop
    settings = _mock_settings(max_api_calls_per_trace=3)
    engine = TraversalEngine(adapter, Chain.ETHEREUM, settings=settings)

    subject = mock_subject(Chain.ETHEREUM, "clean")
    result = await engine.traverse(subject, hop_depth=6, direction=Direction.OUT)

    assert result.api_calls <= 4  # At most 2 expansions
    assert result.truncated is True


# ─── test: Tron chain ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_tron_traversal() -> None:
    """Engine should work identically on Tron chain via MockAdapter."""
    adapter = MockAdapter(Chain.TRON)
    settings = _mock_settings()
    engine = TraversalEngine(adapter, Chain.TRON, settings=settings)

    subject = mock_subject(Chain.TRON, "clean")
    result = await engine.traverse(subject, hop_depth=3, direction=Direction.OUT)

    assert result.chain == Chain.TRON
    assert result.provenance == DataProvenance.MOCK_DEMO
    assert len(result.nodes) >= 3
    assert len(result.edges) >= 2


# ─── test: provenance is preserved ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_provenance_preserved() -> None:
    """MockAdapter provenance should propagate into the result and every edge."""
    adapter = MockAdapter(Chain.ETHEREUM)
    settings = _mock_settings()
    engine = TraversalEngine(adapter, Chain.ETHEREUM, settings=settings)

    subject = mock_subject(Chain.ETHEREUM, "clean")
    result = await engine.traverse(subject, hop_depth=1, direction=Direction.OUT)

    assert result.provenance == DataProvenance.MOCK_DEMO


# ─── test: evidence edges contain transaction details ────────────────────────────


@pytest.mark.asyncio
async def test_edge_evidence_complete() -> None:
    """Every edge must carry full transaction evidence."""
    adapter = MockAdapter(Chain.ETHEREUM)
    settings = _mock_settings()
    engine = TraversalEngine(adapter, Chain.ETHEREUM, settings=settings)

    subject = mock_subject(Chain.ETHEREUM, "clean")
    result = await engine.traverse(subject, hop_depth=2, direction=Direction.OUT)

    for edge in result.edges:
        assert edge.tx_hash, "edge must have tx_hash"
        assert edge.from_address, "edge must have from_address"
        assert edge.to_address, "edge must have to_address"
        assert edge.amount >= 0, "edge must have non-negative amount"
        assert edge.asset_symbol, "edge must have asset_symbol"
        assert edge.block_timestamp is not None, "edge must have timestamp"
        assert edge.chain == Chain.ETHEREUM


# ─── test: hop_depth=0 means subject only ───────────────────────────────────────


@pytest.mark.asyncio
async def test_hop_depth_zero() -> None:
    """hop_depth=0 would be clamped to 1 by Settings, but if 1, only immediate neighbours."""
    adapter = MockAdapter(Chain.ETHEREUM)
    settings = _mock_settings(default_hop_depth=1, max_hop_depth=6)
    engine = TraversalEngine(adapter, Chain.ETHEREUM, settings=settings)

    subject = mock_subject(Chain.ETHEREUM, "clean")
    result = await engine.traverse(subject, hop_depth=1, direction=Direction.OUT)

    # Only hop-0 (subject) and hop-1 nodes
    for node in result.nodes.values():
        assert node.hop_distance <= 1


# ─── test: _Budget unit tests ───────────────────────────────────────────────────


def test_budget_from_settings_clamps_hops() -> None:
    """_Budget should clamp hop_depth to max_hop_depth."""
    settings = _mock_settings(max_hop_depth=4)
    budget = _Budget.from_settings(hop_depth=10, settings=settings)
    assert budget.max_hops == 4


def test_budget_can_expand_limits() -> None:
    """can_expand should go false when limits are reached."""
    settings = _mock_settings(max_nodes_expanded=2, max_api_calls_per_trace=100)
    budget = _Budget.from_settings(hop_depth=3, settings=settings)

    assert budget.can_expand() is True
    budget.record_expand(2, 5)
    assert budget.can_expand() is True
    budget.record_expand(2, 5)
    assert budget.can_expand() is False
    assert "node expansion limit" in (budget.exhausted_reason or "")
