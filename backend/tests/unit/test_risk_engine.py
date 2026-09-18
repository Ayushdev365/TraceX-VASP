"""Tests for the Phase 9 deterministic risk engine."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from app.graph.types import GraphEdge, GraphNode, TraversalResult
from app.risk import detect_risk_indicators
from app.risk.types import DetectionBasis, RiskIndicatorKind
from app.schemas.common import Chain, DataProvenance, Direction, NodeRole, Severity


def _edge(
    from_addr: str,
    to_addr: str,
    amount: str = "10",
    *,
    tx_hash: str | None = None,
    minutes: int = 0,
    hop: int = 1,
) -> GraphEdge:
    return GraphEdge(
        from_address=from_addr,
        to_address=to_addr,
        tx_hash=tx_hash or f"tx_{from_addr}_{to_addr}_{amount}_{minutes}",
        chain=Chain.ETHEREUM,
        direction=Direction.OUT,
        asset_symbol="ETH",
        amount=Decimal(amount),
        block_timestamp=datetime(2026, 1, 1, tzinfo=UTC) + timedelta(minutes=minutes),
        hop_index=hop,
        dedup_key=f"dedup_{from_addr}_{to_addr}_{amount}_{minutes}_{hop}",
    )


def _result() -> TraversalResult:
    res = TraversalResult(
        subject_address="sub",
        chain=Chain.ETHEREUM,
        hop_depth=3,
        direction=Direction.OUT,
        provenance=DataProvenance.MOCK_DEMO,
    )
    res.nodes["sub"] = GraphNode("sub", NodeRole.SUBJECT, 0)
    res.paths["sub"] = ("sub",)
    return res


def test_labelled_mixer_bridge_and_sanctioned_indicators() -> None:
    res = _result()
    res.nodes["mix"] = GraphNode("mix", NodeRole.RISK_ENTITY, 1, matched_risk_entity_kind="mixer")
    res.nodes["bridge"] = GraphNode(
        "bridge", NodeRole.RISK_ENTITY, 1, matched_risk_entity_kind="bridge"
    )
    res.nodes["sdn"] = GraphNode(
        "sdn", NodeRole.RISK_ENTITY, 1, matched_risk_entity_kind="sanctioned"
    )
    res.edges.extend(
        [
            _edge("sub", "mix", tx_hash="tx_mix"),
            _edge("sub", "bridge", tx_hash="tx_bridge"),
            _edge("sub", "sdn", tx_hash="tx_sdn"),
        ]
    )

    indicators = detect_risk_indicators(res)
    kinds = {indicator.kind for indicator in indicators}

    assert RiskIndicatorKind.MIXER_INTERACTION in kinds
    assert RiskIndicatorKind.BRIDGE_INTERACTION in kinds
    assert RiskIndicatorKind.SANCTIONED_OR_RISK_ENTITY_INTERACTION in kinds
    labelled = [
        indicator
        for indicator in indicators
        if indicator.kind
        in {
            RiskIndicatorKind.MIXER_INTERACTION,
            RiskIndicatorKind.BRIDGE_INTERACTION,
            RiskIndicatorKind.SANCTIONED_OR_RISK_ENTITY_INTERACTION,
        }
    ]
    assert all(
        indicator.detection_basis is DetectionBasis.LABELLED_ADDRESS for indicator in labelled
    )


def test_high_fan_in_and_high_fan_out_indicators() -> None:
    res = _result()
    for i in range(10):
        res.edges.append(_edge(f"in_{i}", "hub", tx_hash=f"tx_in_{i}"))
        res.edges.append(_edge("spray", f"out_{i}", tx_hash=f"tx_out_{i}"))

    indicators = detect_risk_indicators(res)
    by_kind = {indicator.kind: indicator for indicator in indicators}

    assert by_kind[RiskIndicatorKind.HIGH_FAN_IN].severity is Severity.MEDIUM
    assert by_kind[RiskIndicatorKind.HIGH_FAN_IN].evidence_addresses == ("hub",)
    assert by_kind[RiskIndicatorKind.HIGH_FAN_OUT].evidence_addresses == ("spray",)


def test_rapid_movement_indicator_uses_ordered_path_evidence() -> None:
    res = _result()
    res.nodes["a"] = GraphNode("a", NodeRole.INTERMEDIATE, 1)
    res.nodes["b"] = GraphNode("b", NodeRole.INTERMEDIATE, 2)
    res.paths["a"] = ("sub", "a")
    res.paths["b"] = ("sub", "a", "b")
    res.edges.append(_edge("sub", "a", tx_hash="tx1", minutes=0, hop=1))
    res.edges.append(_edge("a", "b", tx_hash="tx2", minutes=5, hop=2))

    indicators = detect_risk_indicators(res)
    rapid = [item for item in indicators if item.kind is RiskIndicatorKind.RAPID_MOVEMENT]

    assert len(rapid) == 1
    assert rapid[0].evidence_addresses == ("sub", "a", "b")
    assert rapid[0].evidence_tx_hashes == ("tx1", "tx2")


def test_unusual_transaction_pattern_for_uniform_splitting() -> None:
    res = _result()
    for i in range(3):
        res.edges.append(_edge("sub", f"peer_{i}", amount="10.00", tx_hash=f"tx_split_{i}"))

    indicators = detect_risk_indicators(res)
    unusual = [
        item for item in indicators if item.kind is RiskIndicatorKind.UNUSUAL_TRANSACTION_PATTERN
    ]

    assert len(unusual) == 1
    assert unusual[0].detection_basis is DetectionBasis.HEURISTIC
    assert unusual[0].details["outgoing_edges"] == 3


def test_clean_synthetic_path_has_no_risk_indicators() -> None:
    res = _result()
    res.nodes["a"] = GraphNode("a", NodeRole.INTERMEDIATE, 1)
    res.nodes["vasp"] = GraphNode("vasp", NodeRole.VASP, 2)
    res.paths["a"] = ("sub", "a")
    res.paths["vasp"] = ("sub", "a", "vasp")
    res.edges.append(_edge("sub", "a", amount="11", tx_hash="tx1", minutes=0))
    res.edges.append(_edge("a", "vasp", amount="7", tx_hash="tx2", minutes=120, hop=2))

    assert detect_risk_indicators(res) == []


def test_indicator_copy_is_neutral() -> None:
    res = _result()
    res.nodes["mix"] = GraphNode("mix", NodeRole.RISK_ENTITY, 1, matched_risk_entity_kind="mixer")
    res.edges.append(_edge("sub", "mix"))

    forbidden = ("criminal", "launderer", "guilty")
    rendered = " ".join(indicator.summary.lower() for indicator in detect_risk_indicators(res))

    assert not any(term in rendered for term in forbidden)
