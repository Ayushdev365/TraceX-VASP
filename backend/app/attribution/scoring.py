"""Deterministic scoring engine for VASP attribution."""

from __future__ import annotations

from app.attribution.candidates import aggregate_candidates
from app.attribution.config import (
    BASE_SCORE,
    HOP_MULTIPLIERS,
    MIN_ATTRIBUTION_SCORE,
    WEIGHTS,
    get_score_band,
)
from app.attribution.explain import generate_why_summary
from app.graph.types import TraversalResult
from app.risk.config import MAX_TOTAL_RISK_PENALTY
from app.risk.engine import risk_penalty_for_path
from app.risk.types import RiskIndicator
from app.schemas.attribution import ScoreBreakdown, ScoredCandidate


def score_candidates(
    result: TraversalResult,
    risk_indicators: list[RiskIndicator] | None = None,
) -> list[ScoredCandidate]:
    """Score all candidate VASPs discovered in a traversal result.

    Returns a list of ScoredCandidate objects, sorted by rank (highest score first).
    """
    aggregated = aggregate_candidates(result)
    scored = []

    # Pre-calculate total volume across all edges in the graph to determine volume_share
    total_graph_volume = sum(float(e.amount) for e in result.edges) if result.edges else 0.0

    for _, agg in enumerate(aggregated):
        # Calculate interactions (tx_count and volume terminating at this candidate)
        tx_count = 0
        volume = 0.0

        # We consider any edge that touches one of the candidate's matched addresses
        for edge in result.edges:
            if (
                edge.from_address in agg.matched_addresses
                or edge.to_address in agg.matched_addresses
            ):
                tx_count += 1
                volume += float(edge.amount)

        # 1. Hop Penalty
        hop_penalty = HOP_MULTIPLIERS.get(agg.min_hop_distance, 0.0)

        # 2. Transaction Count Factor (saturates at 10 transactions)
        tx_count_factor = min(1.0, tx_count / 10.0)

        # 3. Volume Factor (saturates at 25% of total graph volume, or absolute value if needed)
        # Using a simple share of total graph volume
        volume_share = (volume / total_graph_volume) if total_graph_volume > 0 else 0.0
        volume_factor = min(1.0, volume_share / 0.25)

        # 4. Reliability Factor (stubbed to 1.0 for now, could be passed in from the label matcher)
        reliability_factor = 1.0

        # Calculate raw contributions based on weights
        contributions = {
            "hop_distance": hop_penalty * WEIGHTS["hop_distance"] * BASE_SCORE,
            "tx_count": tx_count_factor * WEIGHTS["tx_count"] * BASE_SCORE,
            "volume": volume_factor * WEIGHTS["volume"] * BASE_SCORE,
        }

        base_score = sum(contributions.values())

        best_path = min(agg.paths, key=len) if agg.paths else ()
        risk_penalty, matching_indicators = risk_penalty_for_path(
            risk_indicators or [],
            best_path,
            cap=MAX_TOTAL_RISK_PENALTY,
        )
        penalty_points = risk_penalty * BASE_SCORE

        final_score = int(base_score - penalty_points)
        # Clamp to 0-100
        final_score = max(0, min(100, final_score))

        score_band = get_score_band(final_score)

        breakdown = ScoreBreakdown(
            base_score=BASE_SCORE,
            hop_penalty=hop_penalty,
            tx_count_factor=tx_count_factor,
            volume_factor=volume_factor,
            reliability_factor=reliability_factor,
            final_score=final_score,
            score_band=score_band,
            why_summary="",  # Generated below
            contributions=contributions,
            risk_penalties=[
                {"kind": indicator.kind.value, "penalty": indicator.penalty}
                for indicator in matching_indicators
            ],
            penalty_total=risk_penalty,
        )

        breakdown.why_summary = generate_why_summary(breakdown, agg.min_hop_distance, agg.vasp_name)

        scored.append(
            ScoredCandidate(
                vasp_name=agg.vasp_name,
                vasp_slug=agg.vasp_slug,
                rank=0,  # Computed below after sorting
                is_primary=False,
                score=final_score,
                score_band=score_band,
                min_hop_distance=agg.min_hop_distance,
                matched_addresses=list(agg.matched_addresses),
                interaction_tx_count=tx_count,
                interaction_value_usd=volume,  # Abstract value, doesn't have to be USD strictly
                score_breakdown=breakdown,
                evidence_paths=[list(p) for p in agg.paths],
            )
        )

    # Sort descending by score, then ascending by hop distance, then alphabetically
    scored.sort(key=lambda s: (-s.score, s.min_hop_distance, s.vasp_name))

    # Assign ranks and is_primary
    for i, candidate in enumerate(scored):
        candidate.rank = i + 1
        if i == 0 and candidate.score >= MIN_ATTRIBUTION_SCORE:
            candidate.is_primary = True

    return scored
