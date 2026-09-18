"""Shared response schemas and cross-chain enumerations.

These mirror ``docs/API_CONTRACT.md`` sec.2. Enumerations are defined once here and reused by
the adapters, the graph engine and the API layer so a value cannot drift between layers.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class Chain(StrEnum):
    """Chains the system knows about. MVP support is ETHEREUM + TRON (DPRD sec.11)."""

    ETHEREUM = "ethereum"
    TRON = "tron"
    BITCOIN = "bitcoin"
    BNB = "bnb"
    SOLANA = "solana"
    POLYGON = "polygon"


#: Chains whose adapters are implemented for the MVP. Everything else is roadmap.
MVP_CHAINS: frozenset[Chain] = frozenset({Chain.ETHEREUM, Chain.TRON})


class ChainStatus(StrEnum):
    SUPPORTED = "supported"
    DEGRADED = "degraded"  # adapter configured but its last health probe failed
    ROADMAP = "roadmap"


class DataProvenance(StrEnum):
    """Where a response's chain data came from. Never absent from a data-bearing payload."""

    LIVE_API = "live_api"
    CACHED = "cached"
    MOCK_DEMO = "mock_demo"
    MIXED = "mixed"


class NodeRole(StrEnum):
    SUBJECT = "subject"
    INTERMEDIATE = "intermediate"
    VASP = "vasp"
    RISK_ENTITY = "risk_entity"
    CONTRACT = "contract"


class TxKind(StrEnum):
    NATIVE = "native"
    TOKEN = "token"
    INTERNAL = "internal"


class TxStatus(StrEnum):
    SUCCESS = "success"
    FAILED = "failed"


class Direction(StrEnum):
    IN = "in"
    OUT = "out"


class LabelTier(StrEnum):
    """Label reliability tiers, highest trust first (DPRD sec.16)."""

    OFFICIAL_VASP_PUBLISHED = "official_vasp_published"
    SANCTIONS_LIST = "sanctions_list"
    COMMUNITY_VERIFIED = "community_verified"
    COMMUNITY_UNVERIFIED = "community_unverified"
    DEMO_UNVERIFIED = "demo_unverified"


class VerificationStatus(StrEnum):
    VERIFIED = "verified"
    UNVERIFIED = "unverified"
    DISPUTED = "disputed"


class Severity(StrEnum):
    INFO = "info"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class ScoreBand(StrEnum):
    INSUFFICIENT = "insufficient"
    LOW = "low"
    MODERATE = "moderate"
    STRONG = "strong"
    VERY_STRONG = "very_strong"


class VaspKind(StrEnum):
    EXCHANGE = "exchange"
    CUSTODIAL_WALLET = "custodial_wallet"
    PAYMENT_PROCESSOR = "payment_processor"
    OTC_DESK = "otc_desk"
    BROKER = "broker"


class AddressType(StrEnum):
    HOT_WALLET = "hot_wallet"
    DEPOSIT = "deposit"
    COLD_WALLET = "cold_wallet"
    CONTRACT = "contract"


class RiskEntityKind(StrEnum):
    MIXER = "mixer"
    BRIDGE = "bridge"
    GAMBLING = "gambling"
    DARKNET_MARKET = "darknet_market"
    SANCTIONED = "sanctioned"
    SCAM_REPORTED = "scam_reported"


class TraceStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    PARTIAL = "partial"
    FAILED = "failed"


class ReviewDecision(StrEnum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    DEEPER_TRACE_REQUESTED = "deeper_trace_requested"


class ReportFormat(StrEnum):
    JSON = "json"
    PDF = "pdf"


class CaseStatus(StrEnum):
    OPEN = "open"
    UNDER_REVIEW = "under_review"
    CLOSED = "closed"


class UserRole(StrEnum):
    INVESTIGATOR = "investigator"
    ANALYST = "analyst"
    ADMIN = "admin"


class DisclosureMode(StrEnum):
    """Only one value exists in the MVP: nothing can be submitted live (DPRD sec.29)."""

    MOCK_DEMO = "mock_demo"


class CoverageLevel(StrEnum):
    """How much of a chain's label space the dataset covers. Never claims completeness."""

    NONE = "none"
    LIMITED = "limited"
    PARTIAL = "partial"


#: Label tiers that may, on their own, support a primary attribution. A match backed only by
#: ``demo_unverified`` evidence is refused outright (DPRD sec.16; brief: never treat an
#: unverified address as verified).
ATTRIBUTABLE_TIERS: frozenset[LabelTier] = frozenset(
    {
        LabelTier.OFFICIAL_VASP_PUBLISHED,
        LabelTier.SANCTIONS_LIST,
        LabelTier.COMMUNITY_VERIFIED,
        LabelTier.COMMUNITY_UNVERIFIED,
    }
)

#: Default reliability weight per tier, used by the scorer (Phase 8) and as the importer's
#: default when a source does not state its own reliability.
TIER_RELIABILITY: dict[LabelTier, float] = {
    LabelTier.OFFICIAL_VASP_PUBLISHED: 1.00,
    LabelTier.SANCTIONS_LIST: 1.00,
    LabelTier.COMMUNITY_VERIFIED: 0.75,
    LabelTier.COMMUNITY_UNVERIFIED: 0.55,
    LabelTier.DEMO_UNVERIFIED: 0.25,
}


class ApiModel(BaseModel):
    """Base for every response model: reject unknown fields, allow ORM attribute reads."""

    model_config = ConfigDict(from_attributes=True, extra="forbid")


class ErrorDetail(ApiModel):
    code: str
    message: str
    details: dict[str, Any] = Field(default_factory=dict)
    request_id: str | None = None


class ErrorResponse(ApiModel):
    """The uniform error envelope (``docs/API_CONTRACT.md`` sec.5)."""

    error: ErrorDetail


class DependencyHealth(ApiModel):
    name: str
    status: Literal["ok", "not_configured", "degraded", "unavailable"]
    detail: str | None = None


class HealthResponse(ApiModel):
    status: Literal["ok", "degraded"]
    engine_version: str
    app_env: str
    time: str
    dependencies: list[DependencyHealth]
