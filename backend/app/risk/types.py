"""Risk indicator data types.

Risk indicators are explainable attention markers. They never assert criminality and
never replace the separate VASP attribution decision.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from app.schemas.common import Severity


class RiskIndicatorKind(StrEnum):
    MIXER_INTERACTION = "mixer_interaction"
    BRIDGE_INTERACTION = "bridge_interaction"
    SANCTIONED_OR_RISK_ENTITY_INTERACTION = "sanctioned_or_risk_entity_interaction"
    HIGH_FAN_IN = "high_fan_in"
    HIGH_FAN_OUT = "high_fan_out"
    RAPID_MOVEMENT = "rapid_movement"
    UNUSUAL_TRANSACTION_PATTERN = "unusual_transaction_pattern"


class DetectionBasis(StrEnum):
    LABELLED_ADDRESS = "labelled_address"
    HEURISTIC = "heuristic"


@dataclass(frozen=True, slots=True)
class RiskIndicator:
    """One evidence-backed risk indicator found in a trace."""

    kind: RiskIndicatorKind
    severity: Severity
    detection_basis: DetectionBasis
    summary: str
    evidence_addresses: tuple[str, ...] = ()
    evidence_tx_hashes: tuple[str, ...] = ()
    penalty: float = 0.0
    details: dict[str, str | int | float] = field(default_factory=dict)
