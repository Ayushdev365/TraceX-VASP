"""Explanation generation for the attribution scorer."""

from __future__ import annotations

from app.schemas.attribution import ScoreBreakdown


def generate_why_summary(breakdown: ScoreBreakdown, min_hop_distance: int, vasp_name: str) -> str:
    """Generate a human-readable summary of why an attribution scored what it did.

    This fulfills the 'explainable' requirement of Phase 8. No probabilities, no ML
    jargon, just facts about hops, volume, and interactions.
    """
    if breakdown.score_band == "insufficient":
        return f"Evidence pointing to {vasp_name} is insufficient to support an attribution."

    sentences = []

    # Hop distance
    if min_hop_distance == 1:
        sentences.append("Direct interaction with the subject.")
    elif min_hop_distance <= 3:
        sentences.append(f"Connected to the subject across {min_hop_distance} hops.")
    else:
        sentences.append(f"Distant connection ({min_hop_distance} hops) limits confidence.")

    # Transaction evidence
    if breakdown.tx_count_factor > 0.8:
        sentences.append("Supported by frequent, repeated interactions.")
    elif breakdown.tx_count_factor > 0.4:
        sentences.append("Multiple transactions establish a regular pattern.")
    else:
        sentences.append("Sparse transaction history.")

    # Volume evidence
    if breakdown.volume_factor > 0.8:
        sentences.append("Represents a dominant share of the observed value flow.")
    elif breakdown.volume_factor > 0.4:
        sentences.append("Accounts for a meaningful portion of transferred value.")

    return " ".join(sentences)
