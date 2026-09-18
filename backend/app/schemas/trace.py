"""Trace investigation request and result schemas."""

from __future__ import annotations

from enum import StrEnum

from pydantic import Field, field_validator

from app.schemas.attribution import ScoredCandidate
from app.schemas.common import (
    ApiModel,
    Chain,
    DataProvenance,
    Direction,
    NodeRole,
    ReviewDecision,
    Severity,
)


class TraceDataMode(StrEnum):
    AUTO = "auto"
    MOCK = "mock"


class TraceRequest(ApiModel):
    address: str = Field(min_length=1, max_length=128)
    chain: Chain
    hop_depth: int = Field(default=3, ge=1, le=6)
    direction: Direction = Direction.OUT
    data_mode: TraceDataMode = TraceDataMode.AUTO
    case_ref: str | None = Field(default=None, max_length=128)

    @field_validator("address")
    @classmethod
    def _strip_address(cls, value: str) -> str:
        return value.strip()

    @field_validator("case_ref")
    @classmethod
    def _strip_case_ref(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None


class DemoSubjectsResponse(ApiModel):
    subjects: dict[Chain, dict[str, str]]


class TraceNodeResult(ApiModel):
    address: str
    role: NodeRole
    hop_distance: int
    expanded: bool
    not_expanded_reason: str | None = None
    matched_vasp_name: str | None = None
    matched_vasp_slug: str | None = None
    matched_risk_entity_kind: str | None = None


class TraceEdgeResult(ApiModel):
    from_address: str
    to_address: str
    tx_hash: str
    chain: Chain
    direction: Direction
    asset_symbol: str
    amount: str
    block_timestamp: str
    hop_index: int


class TraceRiskIndicatorResult(ApiModel):
    kind: str
    severity: Severity
    detection_basis: str
    summary: str
    evidence_addresses: list[str]
    evidence_tx_hashes: list[str]
    penalty: float
    details: dict[str, str | int | float]


class TraceCandidateResult(ApiModel):
    address: str
    vasp_name: str
    vasp_slug: str
    hop_distance: int
    path: list[str]


class TraceResultResponse(ApiModel):
    trace_id: str
    status: str
    queried_address: str
    canonical_address: str
    chain: Chain
    hop_depth: int
    direction: Direction
    data_provenance: DataProvenance
    data_mode: TraceDataMode
    case_ref: str | None = None
    truncated: bool
    truncation_reason: str | None = None
    nodes_expanded: int
    api_calls_made: int
    tx_analyzed_count: int
    duration_ms: int | None = None
    discovered_addresses: list[str]
    nodes: list[TraceNodeResult]
    edges: list[TraceEdgeResult]
    paths: dict[str, list[str]]
    vasp_candidates: list[TraceCandidateResult]
    attributions: list[ScoredCandidate]
    primary_attribution: ScoredCandidate | None = None
    no_attribution_reason: str | None = None
    risk_indicators: list[TraceRiskIndicatorResult]
    evidence_summary: str
    provenance_note: str
    score_type: str = "heuristic_investigative_score"
    calibrated: bool = False


class TraceReviewRequest(ApiModel):
    decision: ReviewDecision
    note: str | None = Field(default=None, max_length=1000)


class TraceReviewResponse(ApiModel):
    trace_id: str
    decision: ReviewDecision
    note: str | None = None


class TraceReportResponse(ApiModel):
    report_ref: str
    trace_id: str
    format: str = "json"
    content_sha256: str
    payload: dict[str, object]


class DisclosureDraftResponse(ApiModel):
    disclosure_ref: str
    trace_id: str
    mode: str = "mock_demo"
    payload_schema_version: str = "mock-sahyog-v1"
    banner: str
    payload: dict[str, object]
