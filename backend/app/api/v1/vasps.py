"""VASP directory and label lookup endpoints."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query

from app.blockchain.addresses import validate_address
from app.config import get_settings
from app.core.errors import InvalidAddress, ResourceNotFound
from app.database.models import RiskEntity, VaspAddress
from app.database.repositories import labels as labels_repo
from app.deps import DbSession, RequireApiKey
from app.schemas.common import ATTRIBUTABLE_TIERS, Chain, LabelTier
from app.schemas.label import (
    AddressLookupClaim,
    AddressLookupResponse,
    RiskEntityEntry,
    VaspAddressEntry,
    VaspDetail,
    VaspListResponse,
    VaspSummary,
)

router = APIRouter(tags=["vasps"], dependencies=[RequireApiKey])

CONFLICT_NOTICE = (
    "More than one source attributes this address to a different VASP. Both claims are "
    "shown; the system does not choose between them. Resolve this manually before relying "
    "on either attribution."
)


def _address_entry(row: VaspAddress, stale_days: int) -> VaspAddressEntry:
    age = labels_repo.label_age_days(row.last_updated_at)
    return VaspAddressEntry(
        id=str(row.id),
        chain=Chain(row.chain),
        address=row.address,
        address_type=row.address_type,
        source=row.source,
        source_url=row.source_url,
        source_tier=LabelTier(row.source_tier),
        verification_status=row.verification_status,
        reliability=float(row.reliability),
        label_age_days=age,
        is_stale=age > stale_days,
        notes=row.notes,
    )


def _risk_entry(row: RiskEntity) -> RiskEntityEntry:
    return RiskEntityEntry(
        id=str(row.id),
        chain=Chain(row.chain),
        address=row.address,
        entity_kind=row.entity_kind,
        entity_name=row.entity_name,
        severity=row.severity,
        source=row.source,
        source_url=row.source_url,
        source_tier=LabelTier(row.source_tier),
        verification_status=row.verification_status,
    )


@router.get("/vasps", response_model=VaspListResponse, summary="List known VASPs")
async def list_vasps(
    session: DbSession,
    chain: Annotated[Chain | None, Query()] = None,
    q: Annotated[str | None, Query(max_length=128)] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> VaspListResponse:
    rows, total = await labels_repo.list_vasps(
        session, chain=chain, query=q, limit=limit, offset=offset
    )
    return VaspListResponse(
        vasps=[
            VaspSummary(
                id=str(vasp.id),
                slug=vasp.slug,
                name=vasp.name,
                kind=vasp.kind,
                jurisdiction=vasp.jurisdiction,
                is_fiu_ind_registered=vasp.is_fiu_ind_registered,
                website=vasp.website,
                address_count=count,
                chains=[Chain(value) for value in chains],
            )
            for vasp, count, chains in rows
        ],
        total=total,
    )


@router.get(
    "/vasps/addresses",
    response_model=AddressLookupResponse,
    summary="Check an address against the labelled datasets",
)
async def lookup_address(
    session: DbSession,
    chain: Annotated[Chain, Query()],
    address: Annotated[str, Query(min_length=1, max_length=128)],
) -> AddressLookupResponse:
    """Look up one address.

    The address is canonicalised first: querying with a checksummed Ethereum address or a
    Tron hex address must find the same row as its canonical form, or matching would produce
    silent false negatives (DPRD sec.17).
    """
    validation = validate_address(address, chain)
    if not validation.valid or validation.canonical_address is None:
        raise InvalidAddress(
            validation.error_message or "The address is not valid for this chain.",
            details={
                "code": validation.error_code.value if validation.error_code else None,
                "suggested_chain": (
                    validation.suggested_chain.value if validation.suggested_chain else None
                ),
            },
        )

    canonical = validation.canonical_address
    found = await labels_repo.lookup_address(session, chain, canonical)
    stale_days = get_settings().stale_label_days

    return AddressLookupResponse(
        chain=chain,
        query_address=address,
        canonical_address=canonical,
        is_labelled=found.is_vasp or found.is_risk_entity,
        vasp_claims=[
            AddressLookupClaim(
                vasp_id=str(row.vasp_id),
                vasp_slug=row.vasp.slug,
                vasp_name=row.vasp.name,
                entry=_address_entry(row, stale_days),
            )
            for row in found.vasp_addresses
        ],
        risk_entities=[_risk_entry(row) for row in found.risk_entities],
        has_conflicting_labels=found.has_conflicting_labels,
        conflict_notice=CONFLICT_NOTICE if found.has_conflicting_labels else None,
    )


@router.get(
    "/vasps/{slug}",
    response_model=VaspDetail,
    summary="One VASP with its labelled addresses",
)
async def get_vasp(session: DbSession, slug: str) -> VaspDetail:
    vasp = await labels_repo.get_vasp_by_slug(session, slug)
    if vasp is None:
        raise ResourceNotFound(f"No VASP with slug {slug!r}.")

    stale_days = get_settings().stale_label_days
    active = [row for row in vasp.addresses if row.is_active]

    return VaspDetail(
        id=str(vasp.id),
        slug=vasp.slug,
        name=vasp.name,
        kind=vasp.kind,
        jurisdiction=vasp.jurisdiction,
        is_fiu_ind_registered=vasp.is_fiu_ind_registered,
        website=vasp.website,
        legal_entity=vasp.legal_entity,
        nodal_officer_channel=vasp.nodal_officer_channel,
        notes=vasp.notes,
        address_count=len(active),
        chains=[Chain(value) for value in sorted({row.chain for row in active})],
        addresses=[_address_entry(row, stale_days) for row in active],
    )


def can_support_attribution(tier: LabelTier) -> bool:
    """Whether a label of this tier may, on its own, support a primary attribution."""
    return tier in ATTRIBUTABLE_TIERS
