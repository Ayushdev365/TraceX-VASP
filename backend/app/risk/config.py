"""Configuration constants for deterministic risk indicators."""

from __future__ import annotations

from app.risk.types import RiskIndicatorKind

HIGH_FAN_IN_THRESHOLD = 10
HIGH_FAN_OUT_THRESHOLD = 10
RAPID_MOVEMENT_SECONDS = 10 * 60
UNIFORM_SPLIT_MIN_EDGES = 3
UNIFORM_SPLIT_TOLERANCE = 0.01

RISK_PENALTIES: dict[RiskIndicatorKind, float] = {
    RiskIndicatorKind.MIXER_INTERACTION: 0.25,
    RiskIndicatorKind.BRIDGE_INTERACTION: 0.15,
    RiskIndicatorKind.SANCTIONED_OR_RISK_ENTITY_INTERACTION: 0.10,
    RiskIndicatorKind.HIGH_FAN_IN: 0.08,
    RiskIndicatorKind.HIGH_FAN_OUT: 0.10,
    RiskIndicatorKind.RAPID_MOVEMENT: 0.05,
    RiskIndicatorKind.UNUSUAL_TRANSACTION_PATTERN: 0.05,
}

MAX_TOTAL_RISK_PENALTY = 0.50
