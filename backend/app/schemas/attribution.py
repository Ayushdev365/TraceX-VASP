"""Schemas for attribution scoring."""

from __future__ import annotations

from pydantic import BaseModel, Field


class ScoreBreakdown(BaseModel):
    """Detailed breakdown of how an attribution score was calculated."""

    base_score: int = Field(..., description="Starting score before penalties")
    hop_penalty: float = Field(..., description="Penalty multiplier for hop distance")
    tx_count_factor: float = Field(..., description="Multiplier for transaction count/frequency")
    volume_factor: float = Field(..., description="Multiplier based on transaction volume")
    final_score: int = Field(..., description="Final calculated score (0-100)")
    score_band: str = Field(..., description="insufficient, low, moderate, strong, very_strong")
    why_summary: str = Field(..., description="Human-readable explanation of the score")
    contributions: dict[str, float] = Field(default_factory=dict, description="Raw factor values")
    risk_penalties: list[dict[str, float | str]] = Field(default_factory=list)
    penalty_total: float = 0.0


class ScoredCandidate(BaseModel):
    """A VASP candidate evaluated and scored by the attribution engine."""

    vasp_name: str
    vasp_slug: str
    rank: int = 0
    is_primary: bool = False
    score: int
    score_band: str
    min_hop_distance: int
    matched_addresses: list[str]
    interaction_tx_count: int
    interaction_value_usd: float | None = None
    score_breakdown: ScoreBreakdown
    evidence_paths: list[list[str]] = Field(default_factory=list)
