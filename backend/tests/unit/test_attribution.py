"""Tests for the attribution scoring engine (Phase 8)."""

from datetime import UTC, datetime
from decimal import Decimal

from app.attribution.scoring import score_candidates
from app.graph.types import CandidateVasp, GraphEdge, GraphNode, TraversalResult
from app.risk.types import DetectionBasis, RiskIndicator, RiskIndicatorKind
from app.schemas.attribution import ScoredCandidate
from app.schemas.common import Chain, DataProvenance, Direction, NodeRole, Severity


def _make_edge(from_addr: str, to_addr: str, amount: str, hop: int) -> GraphEdge:
    return GraphEdge(
        from_address=from_addr,
        to_address=to_addr,
        tx_hash=f"tx_{from_addr}_{to_addr}_{amount}",
        chain=Chain.ETHEREUM,
        direction=Direction.OUT,
        asset_symbol="ETH",
        amount=Decimal(amount),
        block_timestamp=datetime.now(UTC),
        hop_index=hop,
        dedup_key=f"dedup_{from_addr}_{to_addr}_{amount}",
    )


def test_no_candidate() -> None:
    """Test that a trace with no candidates returns an empty list."""
    res = TraversalResult(
        subject_address="sub",
        chain=Chain.ETHEREUM,
        hop_depth=3,
        direction=Direction.OUT,
        provenance=DataProvenance.MOCK_DEMO,
    )
    # Give it some nodes but no candidates
    res.nodes["sub"] = GraphNode("sub", NodeRole.SUBJECT, 0)
    res.nodes["i1"] = GraphNode("i1", NodeRole.INTERMEDIATE, 1)

    scored = score_candidates(res)
    assert len(scored) == 0


def test_direct_vasp_interaction() -> None:
    """Test scoring for a 1-hop direct interaction with a VASP."""
    res = TraversalResult(
        subject_address="sub",
        chain=Chain.ETHEREUM,
        hop_depth=1,
        direction=Direction.OUT,
        provenance=DataProvenance.MOCK_DEMO,
    )
    res.nodes["sub"] = GraphNode("sub", NodeRole.SUBJECT, 0)
    res.nodes["vasp1"] = GraphNode(
        "vasp1", NodeRole.VASP, 1, matched_vasp_name="Exchange A", matched_vasp_slug="exch_a"
    )

    # 5 transactions, total volume 500
    for _ in range(5):
        res.edges.append(_make_edge("sub", "vasp1", "100", 1))

    res.candidates.append(CandidateVasp("vasp1", "Exchange A", "exch_a", 1, ("sub", "vasp1")))

    scored = score_candidates(res)

    assert len(scored) == 1
    c = scored[0]
    assert c.vasp_slug == "exch_a"
    assert c.min_hop_distance == 1
    assert c.interaction_tx_count == 5
    assert c.interaction_value_usd == 500.0

    # Check score components
    # Hop = 1 -> 1.0 * 50 = 50
    # Tx count = 5/10 -> 0.5 * 30 = 15
    # Volume = 100% of graph volume -> min(1.0, 1.0/0.25) = 1.0 -> 1.0 * 20 = 20
    # Total = 85
    assert c.score == 85
    assert c.score_band == "very_strong"
    assert c.is_primary is True


def test_multi_hop_candidate_and_weak_evidence() -> None:
    """Test scoring drops correctly over multiple hops and low tx count."""
    res = TraversalResult(
        subject_address="sub",
        chain=Chain.ETHEREUM,
        hop_depth=3,
        direction=Direction.OUT,
        provenance=DataProvenance.MOCK_DEMO,
    )
    res.nodes["sub"] = GraphNode("sub", NodeRole.SUBJECT, 0)
    res.nodes["vasp1"] = GraphNode(
        "vasp1", NodeRole.VASP, 3, matched_vasp_name="Exchange A", matched_vasp_slug="exch_a"
    )

    # 1 transaction at hop 3
    res.edges.append(_make_edge("sub", "i1", "100", 1))
    res.edges.append(_make_edge("i1", "i2", "100", 2))
    res.edges.append(_make_edge("i2", "vasp1", "100", 3))

    res.candidates.append(
        CandidateVasp("vasp1", "Exchange A", "exch_a", 3, ("sub", "i1", "i2", "vasp1"))
    )

    scored = score_candidates(res)

    assert len(scored) == 1
    c = scored[0]

    # Hop = 3 -> 0.5 multiplier -> 0.5 * 50 = 25
    # Tx count = 1 -> 0.1 * 30 = 3
    # Volume = 100 / 300 = 0.33 -> min(1, 0.33/0.25)=1.0 -> 20
    # Total = 25 + 3 + 20 = 48
    assert c.score == 48
    assert c.score_band == "low"
    assert c.is_primary is True


def test_risk_penalty_lowers_score_without_reordering_inputs() -> None:
    """Risk indicators lower the candidate score only when they touch its path."""
    res = TraversalResult(
        subject_address="sub",
        chain=Chain.ETHEREUM,
        hop_depth=2,
        direction=Direction.OUT,
        provenance=DataProvenance.MOCK_DEMO,
    )
    res.edges.append(_make_edge("sub", "risk", "100", 1))
    res.edges.append(_make_edge("risk", "vasp1", "100", 2))
    res.candidates.append(
        CandidateVasp("vasp1", "Exchange A", "exch_a", 2, ("sub", "risk", "vasp1"))
    )

    baseline = score_candidates(res)[0]
    penalized = score_candidates(
        res,
        [
            RiskIndicator(
                kind=RiskIndicatorKind.MIXER_INTERACTION,
                severity=Severity.HIGH,
                detection_basis=DetectionBasis.LABELLED_ADDRESS,
                summary="Path touches an address labelled as a mixer service.",
                evidence_addresses=("risk",),
                evidence_tx_hashes=("tx_sub_risk_100",),
                penalty=0.25,
            )
        ],
    )[0]

    assert penalized.score == baseline.score - 25
    assert penalized.score_breakdown.penalty_total == 0.25
    assert penalized.score_breakdown.risk_penalties[0]["kind"] == "mixer_interaction"


def test_multiple_vasp_candidates_and_ordering() -> None:
    """Test that multiple candidates are scored and ranked correctly."""
    res = TraversalResult(
        subject_address="sub",
        chain=Chain.ETHEREUM,
        hop_depth=3,
        direction=Direction.OUT,
        provenance=DataProvenance.MOCK_DEMO,
    )
    # Candidate 1: Weak, distant
    res.edges.append(_make_edge("i2", "weak_vasp", "10", 3))
    res.candidates.append(
        CandidateVasp("weak_vasp", "Weak VASP", "weak", 3, ("sub", "i1", "i2", "weak_vasp"))
    )

    # Candidate 2: Strong, direct
    for _ in range(20):  # Saturates tx count
        res.edges.append(_make_edge("sub", "strong_vasp", "50", 1))
    res.candidates.append(
        CandidateVasp("strong_vasp", "Strong VASP", "strong", 1, ("sub", "strong_vasp"))
    )

    scored = score_candidates(res)

    assert len(scored) == 2
    assert scored[0].vasp_slug == "strong"
    assert scored[0].rank == 1
    assert scored[0].is_primary is True

    assert scored[1].vasp_slug == "weak"
    assert scored[1].rank == 2
    assert scored[1].is_primary is False
    assert scored[1].score < scored[0].score


def test_deterministic_repeated_runs() -> None:
    """Test that the same input always produces the exact same scores and ordering."""

    def run_trace() -> list[ScoredCandidate]:
        res = TraversalResult(
            subject_address="sub",
            chain=Chain.ETHEREUM,
            hop_depth=2,
            direction=Direction.OUT,
            provenance=DataProvenance.MOCK_DEMO,
        )
        res.edges.append(_make_edge("sub", "vasp_a", "10", 1))
        res.edges.append(_make_edge("sub", "vasp_b", "10", 1))
        res.candidates.append(CandidateVasp("vasp_b", "VASP B", "vasp_b", 1, ("sub", "vasp_b")))
        res.candidates.append(CandidateVasp("vasp_a", "VASP A", "vasp_a", 1, ("sub", "vasp_a")))
        return score_candidates(res)

    run1 = run_trace()
    run2 = run_trace()

    # Assert deterministic output
    assert len(run1) == 2
    assert run1[0].vasp_slug == run2[0].vasp_slug
    assert run1[1].vasp_slug == run2[1].vasp_slug
    assert run1[0].score == run2[0].score
    assert run1[1].score == run2[1].score
