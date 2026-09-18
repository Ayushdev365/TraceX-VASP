"""VASP directory, label provenance and dataset-coverage response models."""

from __future__ import annotations

from datetime import datetime

from pydantic import Field

from app.schemas.common import (
    ApiModel,
    Chain,
    ChainStatus,
    CoverageLevel,
    LabelTier,
    VerificationStatus,
)


class LabelProvenance(ApiModel):
    """Where a label came from and how much it can be trusted.

    Attached to every attribution so an investigator can judge the label itself, not just
    the score computed from it (DPRD sec.15 confidence transparency).
    """

    vasp_address_id: str
    address: str
    address_type: str | None = None
    source: str
    source_url: str
    source_tier: LabelTier
    verification_status: VerificationStatus
    verified_at: datetime | None = None
    reliability: float = Field(ge=0, le=1)
    label_age_days: int
    is_stale: bool
    #: False for ``demo_unverified``: such a label cannot support a primary attribution.
    can_support_attribution: bool


class VaspSummary(ApiModel):
    id: str
    slug: str
    name: str
    kind: str
    jurisdiction: str | None = None
    #: Null means unknown. Never defaulted to false — it is a factual claim about a business.
    is_fiu_ind_registered: bool | None = None
    website: str | None = None
    address_count: int
    chains: list[Chain]


class VaspAddressEntry(ApiModel):
    id: str
    chain: Chain
    address: str
    address_type: str | None = None
    source: str
    source_url: str
    source_tier: LabelTier
    verification_status: VerificationStatus
    reliability: float
    label_age_days: int
    is_stale: bool
    notes: str | None = None


class VaspDetail(VaspSummary):
    legal_entity: str | None = None
    nodal_officer_channel: str | None = None
    notes: str | None = None
    addresses: list[VaspAddressEntry]


class VaspListResponse(ApiModel):
    vasps: list[VaspSummary]
    total: int


class AddressLookupClaim(ApiModel):
    """One source's claim about an address. Several claims may disagree."""

    vasp_id: str
    vasp_slug: str
    vasp_name: str
    entry: VaspAddressEntry


class RiskEntityEntry(ApiModel):
    id: str
    chain: Chain
    address: str
    entity_kind: str
    entity_name: str | None = None
    severity: str
    source: str
    source_url: str
    source_tier: LabelTier
    verification_status: VerificationStatus


class AddressLookupResponse(ApiModel):
    """Result of checking one address against the labelled datasets."""

    chain: Chain
    query_address: str
    canonical_address: str | None = None
    is_labelled: bool
    vasp_claims: list[AddressLookupClaim]
    risk_entities: list[RiskEntityEntry]
    #: True when sources disagree about the owner. Never resolved automatically (DPRD sec.21).
    has_conflicting_labels: bool
    conflict_notice: str | None = None


class ChainCoverage(ApiModel):
    vasp_count: int
    vasp_address_count: int
    risk_entity_count: int
    label_dataset_version: str | None = None
    label_dataset_age_days: int | None = None
    is_stale: bool
    coverage_level: CoverageLevel
    coverage_notice: str


class ChainInfo(ApiModel):
    chain: Chain
    display_name: str
    native_asset: str
    status: ChainStatus
    adapter_provenance: str | None = None
    providers: list[str]
    coverage: ChainCoverage | None = None


class ChainsResponse(ApiModel):
    chains: list[ChainInfo]
    stale_label_days_threshold: int


class DatasetSourceEntry(ApiModel):
    name: str
    kind: str
    url: str
    file: str
    sha256: str
    tier: str
    licence: str
    retrieved: str


class DatasetVersionSummary(ApiModel):
    id: str
    version: str
    imported_at: datetime
    age_days: int
    is_stale: bool
    vasp_address_count: int
    risk_entity_count: int
    sources: list[DatasetSourceEntry]
    skipped_sources: list[str]
    integrity_is_clean: bool | None = None
    integrity_warning_count: int | None = None


class DatasetVersionsResponse(ApiModel):
    versions: list[DatasetVersionSummary]
    current_version: str | None = None
