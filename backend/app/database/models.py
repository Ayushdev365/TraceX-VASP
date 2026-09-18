"""SQLAlchemy models — the full schema from ``docs/DATA_MODEL.md``.

All tables land in one migration even though most are not read until later phases. The
alternative — a migration per phase — would mean re-shaping tables that already hold demo
data mid-build, which is exactly the churn a hackathon timeline cannot absorb.

Two invariants are enforced by the database itself rather than by application code, because
they are the ones that would damage the product's honesty if they ever slipped:

1. A label cannot claim ``verified`` without a ``verified_at`` timestamp.
2. A ``demo_unverified`` label cannot claim any verification status but ``unverified``.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any, ClassVar

import sqlalchemy as sa
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from app.database.types import (
    ADDRESS_LEN,
    AMOUNT_RAW_LEN,
    TX_HASH_LEN,
    Amount,
    JSONType,
    Timestamp,
    enum_check,
)
from app.schemas.common import (
    AddressType,
    CaseStatus,
    Chain,
    DataProvenance,
    Direction,
    DisclosureMode,
    LabelTier,
    NodeRole,
    ReportFormat,
    ReviewDecision,
    RiskEntityKind,
    ScoreBand,
    Severity,
    TraceStatus,
    TxKind,
    TxStatus,
    UserRole,
    VaspKind,
    VerificationStatus,
)


class Base(DeclarativeBase):
    """Declarative base. ``metadata`` here is what Alembic compares against."""

    type_annotation_map: ClassVar[dict[Any, Any]] = {
        dict[str, Any]: JSONType,
        list[Any]: JSONType,
    }


def _uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(sa.Uuid, primary_key=True, default=uuid.uuid4)


def _created_at() -> Mapped[datetime]:
    return mapped_column(Timestamp(), nullable=False, server_default=sa.func.now())


# ─── identity & cases ───────────────────────────────────────────────────────────


class User(Base):
    """MVP ships a single demo identity; the shape is RBAC-ready for Pilot (DPRD sec.31)."""

    __tablename__ = "users"
    __table_args__ = (enum_check("role", UserRole, name="ck_users_role"),)

    id: Mapped[uuid.UUID] = _uuid_pk()
    email: Mapped[str] = mapped_column(sa.String(255), unique=True, nullable=False)
    full_name: Mapped[str | None] = mapped_column(sa.String(255))
    role: Mapped[str] = mapped_column(
        sa.String(32), nullable=False, default=UserRole.INVESTIGATOR.value
    )
    agency: Mapped[str | None] = mapped_column(sa.String(255))
    designation: Mapped[str | None] = mapped_column(sa.String(255))
    is_active: Mapped[bool] = mapped_column(sa.Boolean, nullable=False, default=True)
    last_login_at: Mapped[datetime | None] = mapped_column(Timestamp())
    created_at: Mapped[datetime] = _created_at()


class Case(Base):
    """Groups several wallet lookups under one investigation (DPRD F10)."""

    __tablename__ = "cases"
    __table_args__ = (
        enum_check("status", CaseStatus, name="ck_cases_status"),
        sa.Index("ix_cases_status_created", "status", "created_at"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    case_ref: Mapped[str] = mapped_column(sa.String(64), unique=True, nullable=False)
    title: Mapped[str | None] = mapped_column(sa.String(255))
    description: Mapped[str | None] = mapped_column(sa.Text)
    status: Mapped[str] = mapped_column(
        sa.String(32), nullable=False, default=CaseStatus.OPEN.value
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(sa.ForeignKey("users.id"))
    created_at: Mapped[datetime] = _created_at()
    updated_at: Mapped[datetime | None] = mapped_column(Timestamp(), onupdate=sa.func.now())

    traces: Mapped[list[Trace]] = relationship(back_populates="case")


# ─── observation store ──────────────────────────────────────────────────────────


class Wallet(Base):
    """An address the system has encountered. Holds no keys and no signing material."""

    __tablename__ = "wallets"
    __table_args__ = (
        sa.UniqueConstraint("chain", "address", name="uq_wallets_chain_address"),
        enum_check("chain", Chain, name="ck_wallets_chain"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    chain: Mapped[str] = mapped_column(sa.String(16), nullable=False)
    address: Mapped[str] = mapped_column(sa.String(ADDRESS_LEN), nullable=False)
    address_display: Mapped[str | None] = mapped_column(sa.String(ADDRESS_LEN))
    is_contract: Mapped[bool | None] = mapped_column(sa.Boolean)
    first_seen_at: Mapped[datetime | None] = mapped_column(Timestamp())
    last_seen_at: Mapped[datetime | None] = mapped_column(Timestamp())
    tx_count_observed: Mapped[int | None] = mapped_column(sa.Integer)
    created_at: Mapped[datetime] = _created_at()


class Transaction(Base):
    """Normalized native/internal transfer."""

    __tablename__ = "transactions"
    __table_args__ = (
        sa.UniqueConstraint(
            "chain",
            "tx_hash",
            "from_address",
            "to_address",
            "asset_symbol",
            "kind",
            name="uq_transactions_identity",
        ),
        sa.Index("ix_transactions_from", "chain", "from_address", "block_timestamp"),
        sa.Index("ix_transactions_to", "chain", "to_address", "block_timestamp"),
        sa.Index("ix_transactions_hash", "chain", "tx_hash"),
        enum_check("chain", Chain, name="ck_transactions_chain"),
        enum_check("kind", TxKind, name="ck_transactions_kind"),
        enum_check("status", TxStatus, name="ck_transactions_status"),
        enum_check("provenance", DataProvenance, name="ck_transactions_provenance"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    chain: Mapped[str] = mapped_column(sa.String(16), nullable=False)
    tx_hash: Mapped[str] = mapped_column(sa.String(TX_HASH_LEN), nullable=False)
    block_number: Mapped[int | None] = mapped_column(sa.BigInteger)
    block_timestamp: Mapped[datetime] = mapped_column(Timestamp(), nullable=False)
    from_address: Mapped[str] = mapped_column(sa.String(ADDRESS_LEN), nullable=False)
    to_address: Mapped[str] = mapped_column(sa.String(ADDRESS_LEN), nullable=False)
    asset_symbol: Mapped[str] = mapped_column(sa.String(32), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Amount(), nullable=False)
    amount_raw: Mapped[str] = mapped_column(sa.String(AMOUNT_RAW_LEN), nullable=False)
    decimals: Mapped[int] = mapped_column(sa.SmallInteger, nullable=False)
    kind: Mapped[str] = mapped_column(sa.String(16), nullable=False)
    status: Mapped[str] = mapped_column(sa.String(16), nullable=False)
    fee: Mapped[Decimal | None] = mapped_column(Amount())
    provenance: Mapped[str] = mapped_column(sa.String(16), nullable=False)
    raw_ref: Mapped[uuid.UUID | None] = mapped_column(
        sa.ForeignKey("api_response_cache.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = _created_at()


class TokenTransfer(Base):
    """ERC-20 / TRC-20 movement. Separate from ``transactions``: USDT-on-Tron is the
    dominant rail (DPRD sec.11) and its queries are contract-scoped."""

    __tablename__ = "token_transfers"
    __table_args__ = (
        sa.UniqueConstraint("chain", "tx_hash", "log_index", name="uq_token_transfers_identity"),
        sa.Index("ix_token_transfers_from", "chain", "from_address", "block_timestamp"),
        sa.Index("ix_token_transfers_to", "chain", "to_address", "block_timestamp"),
        sa.Index("ix_token_transfers_contract", "chain", "asset_contract"),
        enum_check("chain", Chain, name="ck_token_transfers_chain"),
        enum_check("status", TxStatus, name="ck_token_transfers_status"),
        enum_check("provenance", DataProvenance, name="ck_token_transfers_provenance"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    chain: Mapped[str] = mapped_column(sa.String(16), nullable=False)
    tx_hash: Mapped[str] = mapped_column(sa.String(TX_HASH_LEN), nullable=False)
    log_index: Mapped[int | None] = mapped_column(sa.Integer)
    block_number: Mapped[int | None] = mapped_column(sa.BigInteger)
    block_timestamp: Mapped[datetime] = mapped_column(Timestamp(), nullable=False)
    from_address: Mapped[str] = mapped_column(sa.String(ADDRESS_LEN), nullable=False)
    to_address: Mapped[str] = mapped_column(sa.String(ADDRESS_LEN), nullable=False)
    asset_symbol: Mapped[str] = mapped_column(sa.String(32), nullable=False)
    asset_contract: Mapped[str] = mapped_column(sa.String(ADDRESS_LEN), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Amount(), nullable=False)
    amount_raw: Mapped[str] = mapped_column(sa.String(AMOUNT_RAW_LEN), nullable=False)
    decimals: Mapped[int] = mapped_column(sa.SmallInteger, nullable=False)
    status: Mapped[str] = mapped_column(sa.String(16), nullable=False)
    fee: Mapped[Decimal | None] = mapped_column(Amount())
    provenance: Mapped[str] = mapped_column(sa.String(16), nullable=False)
    raw_ref: Mapped[uuid.UUID | None] = mapped_column(
        sa.ForeignKey("api_response_cache.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = _created_at()


# ─── labelled datasets ──────────────────────────────────────────────────────────


class LabelDatasetVersion(Base):
    """One import run. Pins which label set produced which result (DPRD sec.15, sec.21)."""

    __tablename__ = "label_dataset_versions"
    __table_args__ = (enum_check("chain", Chain, name="ck_label_versions_chain"),)

    id: Mapped[uuid.UUID] = _uuid_pk()
    version: Mapped[str] = mapped_column(sa.String(64), unique=True, nullable=False)
    chain: Mapped[str | None] = mapped_column(sa.String(16))
    source_manifest: Mapped[dict[str, Any]] = mapped_column(JSONType, nullable=False)
    vasp_address_count: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=0)
    risk_entity_count: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=0)
    imported_by: Mapped[uuid.UUID | None] = mapped_column(sa.ForeignKey("users.id"))
    imported_at: Mapped[datetime] = _created_at()
    integrity_report: Mapped[dict[str, Any] | None] = mapped_column(JSONType)

    vasp_addresses: Mapped[list[VaspAddress]] = relationship(back_populates="dataset_version")


class Vasp(Base):
    """A service provider, independent of how many addresses it owns."""

    __tablename__ = "vasps"
    __table_args__ = (enum_check("kind", VaspKind, name="ck_vasps_kind"),)

    id: Mapped[uuid.UUID] = _uuid_pk()
    slug: Mapped[str] = mapped_column(sa.String(64), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    legal_entity: Mapped[str | None] = mapped_column(sa.String(255))
    kind: Mapped[str] = mapped_column(sa.String(32), nullable=False)
    jurisdiction: Mapped[str | None] = mapped_column(sa.String(8))
    # Null means unknown, never false-by-default: whether an Indian LEA can route a request
    # to this VASP is a factual claim that needs a citable source.
    is_fiu_ind_registered: Mapped[bool | None] = mapped_column(sa.Boolean)
    website: Mapped[str | None] = mapped_column(sa.String(512))
    nodal_officer_channel: Mapped[str | None] = mapped_column(sa.String(512))
    notes: Mapped[str | None] = mapped_column(sa.Text)
    created_at: Mapped[datetime] = _created_at()
    updated_at: Mapped[datetime | None] = mapped_column(Timestamp(), onupdate=sa.func.now())

    addresses: Mapped[list[VaspAddress]] = relationship(
        back_populates="vasp", cascade="all, delete-orphan"
    )


class VaspAddress(Base):
    """The product's core asset (DPRD sec.16, sec.47(22)).

    Provenance columns are NOT NULL by design: the importer cannot insert a label it cannot
    attribute to a citable source.
    """

    __tablename__ = "vasp_addresses"
    __table_args__ = (
        # Two sources asserting the same address are two rows, so agreement *and* conflict
        # are both visible rather than one silently overwriting the other (DPRD sec.21).
        sa.UniqueConstraint(
            "chain", "address", "vasp_id", "source", name="uq_vasp_addresses_identity"
        ),
        sa.Index("ix_vasp_addresses_lookup", "chain", "address"),
        sa.Index("ix_vasp_addresses_vasp", "vasp_id"),
        sa.Index("ix_vasp_addresses_tier", "source_tier"),
        enum_check("chain", Chain, name="ck_vasp_addresses_chain"),
        enum_check("source_tier", LabelTier, name="ck_vasp_addresses_tier"),
        enum_check("verification_status", VerificationStatus, name="ck_vasp_addresses_status"),
        enum_check("address_type", AddressType, name="ck_vasp_addresses_addr_type"),
        sa.CheckConstraint(
            "verification_status <> 'verified' OR verified_at IS NOT NULL",
            name="ck_vasp_addresses_verified_needs_date",
        ),
        sa.CheckConstraint(
            "source_tier <> 'demo_unverified' OR verification_status = 'unverified'",
            name="ck_vasp_addresses_demo_is_unverified",
        ),
        sa.CheckConstraint(
            "reliability >= 0 AND reliability <= 1", name="ck_vasp_addresses_reliability_range"
        ),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    vasp_id: Mapped[uuid.UUID] = mapped_column(
        sa.ForeignKey("vasps.id", ondelete="CASCADE"), nullable=False
    )
    chain: Mapped[str] = mapped_column(sa.String(16), nullable=False)
    address: Mapped[str] = mapped_column(sa.String(ADDRESS_LEN), nullable=False)
    address_type: Mapped[str | None] = mapped_column(sa.String(32))
    source: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    source_url: Mapped[str] = mapped_column(sa.String(1024), nullable=False)
    source_tier: Mapped[str] = mapped_column(sa.String(32), nullable=False)
    verification_status: Mapped[str] = mapped_column(sa.String(16), nullable=False)
    verified_by: Mapped[str | None] = mapped_column(sa.String(255))
    verified_at: Mapped[datetime | None] = mapped_column(Timestamp())
    reliability: Mapped[Decimal] = mapped_column(sa.Numeric(3, 2), nullable=False)
    notes: Mapped[str | None] = mapped_column(sa.Text)
    dataset_version_id: Mapped[uuid.UUID] = mapped_column(
        sa.ForeignKey("label_dataset_versions.id"), nullable=False
    )
    last_updated_at: Mapped[datetime] = _created_at()
    created_at: Mapped[datetime] = _created_at()
    # Soft-retire a withdrawn label instead of deleting it, so an old trace stays explainable.
    is_active: Mapped[bool] = mapped_column(sa.Boolean, nullable=False, default=True)

    vasp: Mapped[Vasp] = relationship(back_populates="addresses")
    dataset_version: Mapped[LabelDatasetVersion] = relationship(back_populates="vasp_addresses")


class RiskEntity(Base):
    """Mixers, bridges, sanctioned addresses — same provenance discipline as labels."""

    __tablename__ = "risk_entities"
    __table_args__ = (
        sa.UniqueConstraint(
            "chain", "address", "entity_kind", "source", name="uq_risk_entities_identity"
        ),
        sa.Index("ix_risk_entities_lookup", "chain", "address"),
        enum_check("chain", Chain, name="ck_risk_entities_chain"),
        enum_check("entity_kind", RiskEntityKind, name="ck_risk_entities_kind"),
        enum_check("severity", Severity, name="ck_risk_entities_severity"),
        enum_check("source_tier", LabelTier, name="ck_risk_entities_tier"),
        enum_check("verification_status", VerificationStatus, name="ck_risk_entities_status"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    chain: Mapped[str] = mapped_column(sa.String(16), nullable=False)
    address: Mapped[str] = mapped_column(sa.String(ADDRESS_LEN), nullable=False)
    entity_kind: Mapped[str] = mapped_column(sa.String(32), nullable=False)
    entity_name: Mapped[str | None] = mapped_column(sa.String(255))
    severity: Mapped[str] = mapped_column(sa.String(16), nullable=False)
    source: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    source_url: Mapped[str] = mapped_column(sa.String(1024), nullable=False)
    source_tier: Mapped[str] = mapped_column(sa.String(32), nullable=False)
    verification_status: Mapped[str] = mapped_column(sa.String(16), nullable=False)
    dataset_version_id: Mapped[uuid.UUID] = mapped_column(
        sa.ForeignKey("label_dataset_versions.id"), nullable=False
    )
    notes: Mapped[str | None] = mapped_column(sa.Text)
    last_updated_at: Mapped[datetime] = _created_at()
    created_at: Mapped[datetime] = _created_at()
    is_active: Mapped[bool] = mapped_column(sa.Boolean, nullable=False, default=True)


# ─── traces (populated from Phase 6) ────────────────────────────────────────────


class Trace(Base):
    """One attribution run, with everything needed to reproduce it byte-for-byte."""

    __tablename__ = "traces"
    __table_args__ = (
        sa.Index("ix_traces_case", "case_id", "created_at"),
        sa.Index("ix_traces_subject", "chain", "subject_address", "created_at"),
        enum_check("chain", Chain, name="ck_traces_chain"),
        enum_check("status", TraceStatus, name="ck_traces_status"),
        enum_check("direction", Direction, name="ck_traces_direction"),
        enum_check("data_provenance", DataProvenance, name="ck_traces_provenance"),
        enum_check("review_decision", ReviewDecision, name="ck_traces_review"),
        sa.CheckConstraint("hop_depth BETWEEN 1 AND 6", name="ck_traces_hop_depth"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    case_id: Mapped[uuid.UUID | None] = mapped_column(sa.ForeignKey("cases.id"))
    subject_address: Mapped[str] = mapped_column(sa.String(ADDRESS_LEN), nullable=False)
    # Exactly what the investigator typed, kept verbatim for the evidence record.
    subject_address_input: Mapped[str] = mapped_column(sa.String(ADDRESS_LEN), nullable=False)
    chain: Mapped[str] = mapped_column(sa.String(16), nullable=False)
    hop_depth: Mapped[int] = mapped_column(sa.SmallInteger, nullable=False)
    direction: Mapped[str] = mapped_column(
        sa.String(8), nullable=False, default=Direction.OUT.value
    )
    status: Mapped[str] = mapped_column(sa.String(16), nullable=False)
    data_provenance: Mapped[str] = mapped_column(sa.String(16), nullable=False)
    truncated: Mapped[bool] = mapped_column(sa.Boolean, nullable=False, default=False)
    truncation_reason: Mapped[str | None] = mapped_column(sa.String(255))
    nodes_expanded: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=0)
    api_calls_made: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=0)
    tx_analyzed_count: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=0)
    duration_ms: Mapped[int | None] = mapped_column(sa.Integer)
    label_dataset_version_id: Mapped[uuid.UUID] = mapped_column(
        sa.ForeignKey("label_dataset_versions.id"), nullable=False
    )
    scoring_config_version: Mapped[str] = mapped_column(sa.String(32), nullable=False)
    budget_config: Mapped[dict[str, Any]] = mapped_column(JSONType, nullable=False)
    engine_version: Mapped[str] = mapped_column(sa.String(32), nullable=False)
    review_decision: Mapped[str] = mapped_column(
        sa.String(32), nullable=False, default=ReviewDecision.PENDING.value
    )
    reviewed_by: Mapped[uuid.UUID | None] = mapped_column(sa.ForeignKey("users.id"))
    reviewed_at: Mapped[datetime | None] = mapped_column(Timestamp())
    review_note: Mapped[str | None] = mapped_column(sa.Text)
    error_message: Mapped[str | None] = mapped_column(sa.String(1024))
    created_by: Mapped[uuid.UUID | None] = mapped_column(sa.ForeignKey("users.id"))
    created_at: Mapped[datetime] = _created_at()

    case: Mapped[Case | None] = relationship(back_populates="traces")
    nodes: Mapped[list[TraceNode]] = relationship(
        back_populates="trace", cascade="all, delete-orphan"
    )
    edges: Mapped[list[TraceEdge]] = relationship(
        back_populates="trace", cascade="all, delete-orphan"
    )
    attributions: Mapped[list[Attribution]] = relationship(
        back_populates="trace", cascade="all, delete-orphan"
    )


class TraceNode(Base):
    __tablename__ = "trace_nodes"
    __table_args__ = (
        sa.UniqueConstraint("trace_id", "address", name="uq_trace_nodes_address"),
        sa.Index("ix_trace_nodes_hop", "trace_id", "hop_distance"),
        enum_check("role", NodeRole, name="ck_trace_nodes_role"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    trace_id: Mapped[uuid.UUID] = mapped_column(
        sa.ForeignKey("traces.id", ondelete="CASCADE"), nullable=False
    )
    address: Mapped[str] = mapped_column(sa.String(ADDRESS_LEN), nullable=False)
    address_display: Mapped[str | None] = mapped_column(sa.String(ADDRESS_LEN))
    role: Mapped[str] = mapped_column(sa.String(16), nullable=False)
    hop_distance: Mapped[int] = mapped_column(sa.SmallInteger, nullable=False)
    matched_vasp_id: Mapped[uuid.UUID | None] = mapped_column(sa.ForeignKey("vasps.id"))
    matched_vasp_address_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.ForeignKey("vasp_addresses.id")
    )
    matched_risk_entity_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.ForeignKey("risk_entities.id")
    )
    in_degree: Mapped[int | None] = mapped_column(sa.Integer)
    out_degree: Mapped[int | None] = mapped_column(sa.Integer)
    counterparty_count: Mapped[int | None] = mapped_column(sa.Integer)
    value_in: Mapped[Decimal | None] = mapped_column(Amount())
    value_out: Mapped[Decimal | None] = mapped_column(Amount())
    expanded: Mapped[bool] = mapped_column(sa.Boolean, nullable=False, default=False)
    not_expanded_reason: Mapped[str | None] = mapped_column(sa.String(64))
    attrs: Mapped[dict[str, Any] | None] = mapped_column(JSONType)

    trace: Mapped[Trace] = relationship(back_populates="nodes")


class TraceEdge(Base):
    __tablename__ = "trace_edges"
    __table_args__ = (
        # dedup_key is computed in the application because the natural key includes a
        # nullable log_index, and NULLs do not compare equal in a UNIQUE constraint.
        sa.UniqueConstraint("trace_id", "dedup_key", name="uq_trace_edges_dedup"),
        sa.Index("ix_trace_edges_hop", "trace_id", "hop_index"),
        sa.Index("ix_trace_edges_evidence", "trace_id", "is_on_evidence_path"),
        enum_check("chain", Chain, name="ck_trace_edges_chain"),
        enum_check("direction", Direction, name="ck_trace_edges_direction"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    trace_id: Mapped[uuid.UUID] = mapped_column(
        sa.ForeignKey("traces.id", ondelete="CASCADE"), nullable=False
    )
    from_node_id: Mapped[uuid.UUID] = mapped_column(
        sa.ForeignKey("trace_nodes.id", ondelete="CASCADE"), nullable=False
    )
    to_node_id: Mapped[uuid.UUID] = mapped_column(
        sa.ForeignKey("trace_nodes.id", ondelete="CASCADE"), nullable=False
    )
    dedup_key: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    chain: Mapped[str] = mapped_column(sa.String(16), nullable=False)
    tx_hash: Mapped[str] = mapped_column(sa.String(TX_HASH_LEN), nullable=False)
    direction: Mapped[str] = mapped_column(sa.String(8), nullable=False)
    asset_symbol: Mapped[str] = mapped_column(sa.String(32), nullable=False)
    asset_contract: Mapped[str | None] = mapped_column(sa.String(ADDRESS_LEN))
    amount: Mapped[Decimal] = mapped_column(Amount(), nullable=False)
    block_timestamp: Mapped[datetime] = mapped_column(Timestamp(), nullable=False)
    hop_index: Mapped[int] = mapped_column(sa.SmallInteger, nullable=False)
    value_share: Mapped[Decimal | None] = mapped_column(sa.Numeric(9, 8))
    is_on_evidence_path: Mapped[bool] = mapped_column(sa.Boolean, nullable=False, default=False)
    attrs: Mapped[dict[str, Any] | None] = mapped_column(JSONType)

    trace: Mapped[Trace] = relationship(back_populates="edges")


class Attribution(Base):
    """One candidate VASP for one trace, so the UI can show a ranked list (DPRD sec.6)."""

    __tablename__ = "attributions"
    __table_args__ = (
        sa.UniqueConstraint("trace_id", "vasp_id", name="uq_attributions_vasp"),
        sa.UniqueConstraint("trace_id", "rank", name="uq_attributions_rank"),
        enum_check("score_band", ScoreBand, name="ck_attributions_band"),
        sa.CheckConstraint("score BETWEEN 0 AND 100", name="ck_attributions_score_range"),
        # The MVP must never emit a score typed as a calibrated probability (DPRD sec.12).
        sa.CheckConstraint(
            "score_type = 'heuristic_investigative_score'", name="ck_attributions_score_type"
        ),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    trace_id: Mapped[uuid.UUID] = mapped_column(
        sa.ForeignKey("traces.id", ondelete="CASCADE"), nullable=False
    )
    vasp_id: Mapped[uuid.UUID] = mapped_column(sa.ForeignKey("vasps.id"), nullable=False)
    rank: Mapped[int] = mapped_column(sa.SmallInteger, nullable=False)
    is_primary: Mapped[bool] = mapped_column(sa.Boolean, nullable=False, default=False)
    score: Mapped[int] = mapped_column(sa.SmallInteger, nullable=False)
    score_band: Mapped[str] = mapped_column(sa.String(16), nullable=False)
    score_type: Mapped[str] = mapped_column(
        sa.String(48), nullable=False, default="heuristic_investigative_score"
    )
    calibrated: Mapped[bool] = mapped_column(sa.Boolean, nullable=False, default=False)
    min_hop_distance: Mapped[int] = mapped_column(sa.SmallInteger, nullable=False)
    matched_address_ids: Mapped[list[Any]] = mapped_column(JSONType, nullable=False)
    interaction_tx_count: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=0)
    interaction_value: Mapped[Decimal | None] = mapped_column(Amount())
    value_share: Mapped[Decimal | None] = mapped_column(sa.Numeric(9, 8))
    score_breakdown: Mapped[dict[str, Any]] = mapped_column(JSONType, nullable=False)
    evidence: Mapped[dict[str, Any]] = mapped_column(JSONType, nullable=False)
    risk_indicators: Mapped[list[Any]] = mapped_column(JSONType, nullable=False)
    # Phase 14 shadow score. Never the decision, never shown as the attribution.
    ml_score: Mapped[int | None] = mapped_column(sa.SmallInteger)
    ml_model_version: Mapped[str | None] = mapped_column(sa.String(64))
    created_at: Mapped[datetime] = _created_at()

    trace: Mapped[Trace] = relationship(back_populates="attributions")


# ─── outputs ────────────────────────────────────────────────────────────────────


class Report(Base):
    """A generated artifact. ``payload`` is stored so the PDF can be re-rendered without
    re-querying any chain (DPRD sec.15 reproducibility)."""

    __tablename__ = "reports"
    __table_args__ = (enum_check("format", ReportFormat, name="ck_reports_format"),)

    id: Mapped[uuid.UUID] = _uuid_pk()
    trace_id: Mapped[uuid.UUID] = mapped_column(
        sa.ForeignKey("traces.id", ondelete="CASCADE"), nullable=False
    )
    format: Mapped[str] = mapped_column(sa.String(8), nullable=False)
    report_ref: Mapped[str] = mapped_column(sa.String(64), unique=True, nullable=False)
    payload: Mapped[dict[str, Any] | None] = mapped_column(JSONType)
    file_path: Mapped[str | None] = mapped_column(sa.String(512))
    content_sha256: Mapped[str | None] = mapped_column(sa.String(64))
    template_version: Mapped[str] = mapped_column(sa.String(32), nullable=False)
    generated_by: Mapped[uuid.UUID | None] = mapped_column(sa.ForeignKey("users.id"))
    generated_at: Mapped[datetime] = _created_at()


class DisclosureRequest(Base):
    """A MOCK SAHYOG draft. Named explicitly so no one mistakes this for a submission log.

    ``mode`` is constrained to a single value: there is no schema-level way to record a live
    submission in the MVP (DPRD sec.29).
    """

    __tablename__ = "disclosure_requests"
    __table_args__ = (enum_check("mode", DisclosureMode, name="ck_disclosure_mode"),)

    id: Mapped[uuid.UUID] = _uuid_pk()
    trace_id: Mapped[uuid.UUID] = mapped_column(
        sa.ForeignKey("traces.id", ondelete="CASCADE"), nullable=False
    )
    attribution_id: Mapped[uuid.UUID] = mapped_column(
        sa.ForeignKey("attributions.id", ondelete="CASCADE"), nullable=False
    )
    vasp_id: Mapped[uuid.UUID] = mapped_column(sa.ForeignKey("vasps.id"), nullable=False)
    draft_ref: Mapped[str] = mapped_column(sa.String(64), unique=True, nullable=False)
    mode: Mapped[str] = mapped_column(
        sa.String(16), nullable=False, default=DisclosureMode.MOCK_DEMO.value
    )
    payload: Mapped[dict[str, Any]] = mapped_column(JSONType, nullable=False)
    payload_schema_version: Mapped[str] = mapped_column(sa.String(32), nullable=False)
    requested_information: Mapped[list[Any]] = mapped_column(JSONType, nullable=False)
    created_by: Mapped[uuid.UUID | None] = mapped_column(sa.ForeignKey("users.id"))
    created_at: Mapped[datetime] = _created_at()


# ─── caching, snapshots, audit ──────────────────────────────────────────────────


class ApiResponseCache(Base):
    """Provider response cache and trace snapshot store in one table.

    A row pinned by a trace (``is_snapshot``) is exempt from eviction, which is what lets a
    report generated today be regenerated months later (DPRD sec.13, sec.15).
    """

    __tablename__ = "api_response_cache"
    __table_args__ = (
        sa.Index("ix_api_cache_expiry", "expires_at"),
        enum_check("chain", Chain, name="ck_api_cache_chain"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    cache_key: Mapped[str] = mapped_column(sa.String(255), unique=True, nullable=False)
    chain: Mapped[str] = mapped_column(sa.String(16), nullable=False)
    provider: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    endpoint: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    # The API key is stripped before this is written; see blockchain/cache.py (Phase 3).
    request_params: Mapped[dict[str, Any]] = mapped_column(JSONType, nullable=False)
    response_body: Mapped[dict[str, Any]] = mapped_column(JSONType, nullable=False)
    http_status: Mapped[int] = mapped_column(sa.SmallInteger, nullable=False)
    fetched_at: Mapped[datetime] = _created_at()
    expires_at: Mapped[datetime | None] = mapped_column(Timestamp())
    is_snapshot: Mapped[bool] = mapped_column(sa.Boolean, nullable=False, default=False)


class TraceSnapshotRef(Base):
    """Pins the exact provider responses that produced a trace."""

    __tablename__ = "trace_snapshot_refs"

    trace_id: Mapped[uuid.UUID] = mapped_column(
        sa.ForeignKey("traces.id", ondelete="CASCADE"), primary_key=True
    )
    api_response_cache_id: Mapped[uuid.UUID] = mapped_column(
        sa.ForeignKey("api_response_cache.id", ondelete="RESTRICT"), primary_key=True
    )


class AuditLog(Base):
    """Append-only action log (DPRD F13)."""

    __tablename__ = "audit_logs"
    __table_args__ = (
        sa.Index("ix_audit_created", "created_at"),
        sa.Index("ix_audit_user", "user_id", "created_at"),
        sa.Index("ix_audit_target", "target_type", "target_id"),
    )

    id: Mapped[int] = mapped_column(sa.BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[uuid.UUID | None] = mapped_column(sa.ForeignKey("users.id"))
    action: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    target_type: Mapped[str | None] = mapped_column(sa.String(32))
    target_id: Mapped[str | None] = mapped_column(sa.String(64))
    # Request summaries only — never API keys, never full request bodies.
    meta: Mapped[dict[str, Any] | None] = mapped_column("metadata", JSONType)
    ip_address: Mapped[str | None] = mapped_column(sa.String(64))
    user_agent: Mapped[str | None] = mapped_column(sa.String(255))
    created_at: Mapped[datetime] = _created_at()


class MlExperiment(Base):
    """Phase 14 training runs. Metrics are written only by the training script, never by
    hand, which is what keeps ``ml/MODEL_CARD.md`` honest."""

    __tablename__ = "ml_experiments"

    id: Mapped[uuid.UUID] = _uuid_pk()
    model_name: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    model_version: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    algorithm: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    feature_set_version: Mapped[str] = mapped_column(sa.String(32), nullable=False)
    train_rows: Mapped[int | None] = mapped_column(sa.Integer)
    test_rows: Mapped[int | None] = mapped_column(sa.Integer)
    split_strategy: Mapped[str | None] = mapped_column(sa.String(64))
    metrics: Mapped[dict[str, Any] | None] = mapped_column(JSONType)
    artifact_path: Mapped[str | None] = mapped_column(sa.String(512))
    notes: Mapped[str | None] = mapped_column(sa.Text)
    created_at: Mapped[datetime] = _created_at()
