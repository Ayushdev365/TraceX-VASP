"""Label dataset version and coverage endpoints.

The coverage notice built here is the product's main defence against a dangerous
misreading: that "no VASP found" means "this wallet has no VASP relationship". It never
does — it means none was found within the current hop cap and label coverage (DPRD sec.21,
sec.27 F03).
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from app.config import get_settings
from app.database.models import LabelDatasetVersion
from app.database.repositories import labels as labels_repo
from app.database.repositories.labels import ChainCoverageStats
from app.deps import DbSession, RequireApiKey
from app.schemas.common import MVP_CHAINS, Chain, ChainStatus, CoverageLevel
from app.schemas.label import (
    ChainCoverage,
    ChainInfo,
    ChainsResponse,
    DatasetSourceEntry,
    DatasetVersionsResponse,
    DatasetVersionSummary,
)

router = APIRouter(tags=["labels"], dependencies=[RequireApiKey])

CHAIN_DISPLAY: dict[Chain, tuple[str, str, tuple[str, ...]]] = {
    # chain -> (display name, native asset, providers)
    Chain.ETHEREUM: ("Ethereum", "ETH", ("etherscan", "bitquery")),
    Chain.TRON: ("Tron", "TRX", ("trongrid", "tronscan", "bitquery")),
    Chain.BITCOIN: ("Bitcoin", "BTC", ("blockchair", "bitquery")),
    Chain.BNB: ("BNB Chain", "BNB", ("bscscan", "bitquery")),
    Chain.SOLANA: ("Solana", "SOL", ("solscan", "bitquery")),
    Chain.POLYGON: ("Polygon", "POL", ("polygonscan", "bitquery")),
}

#: Below this many labelled addresses a chain is described as "limited", not "partial".
LIMITED_COVERAGE_THRESHOLD = 50

NO_COVERAGE_NOTICE = (
    "No labelled addresses for this chain yet. Attribution is not possible until the label "
    "dataset covers it."
)
LIMITED_COVERAGE_NOTICE = (
    "Limited label coverage on this chain. A result of 'no attribution found' is likely to "
    "reflect a coverage gap rather than the absence of a VASP relationship."
)
PARTIAL_COVERAGE_NOTICE = (
    "Partial label coverage. A non-match does not mean the wallet has no VASP relationship — "
    "only that none was found within the current hop cap and label coverage."
)
STALE_NOTICE_SUFFIX = (
    " The label dataset is older than the freshness threshold, so newly-added VASP addresses "
    "may be missing."
)


def build_coverage(
    stats: ChainCoverageStats | None,
    *,
    version: LabelDatasetVersion | None,
    stale_days: int,
) -> ChainCoverage:
    """Turn raw label counts into an honest coverage statement."""
    address_count = stats.vasp_address_count if stats else 0

    if address_count == 0:
        level, notice = CoverageLevel.NONE, NO_COVERAGE_NOTICE
    elif address_count < LIMITED_COVERAGE_THRESHOLD:
        level, notice = CoverageLevel.LIMITED, LIMITED_COVERAGE_NOTICE
    else:
        # Never "complete": the dataset is partial by construction and saying otherwise
        # would be an unsupported claim (DPRD sec.41).
        level, notice = CoverageLevel.PARTIAL, PARTIAL_COVERAGE_NOTICE

    age = labels_repo.label_age_days(version.imported_at) if version else None
    is_stale = age is not None and age > stale_days
    if is_stale:
        notice += STALE_NOTICE_SUFFIX

    return ChainCoverage(
        vasp_count=stats.vasp_count if stats else 0,
        vasp_address_count=address_count,
        risk_entity_count=stats.risk_entity_count if stats else 0,
        label_dataset_version=version.version if version else None,
        label_dataset_age_days=age,
        is_stale=is_stale,
        coverage_level=level,
        coverage_notice=notice,
    )


@router.get(
    "/meta/chains",
    response_model=ChainsResponse,
    summary="Supported chains with adapter status and label coverage",
)
async def list_chains(session: DbSession) -> ChainsResponse:
    settings = get_settings()
    coverage_by_chain = await labels_repo.chain_coverage(session)
    version = await labels_repo.latest_dataset_version(session)

    provider_keys = {
        Chain.ETHEREUM: settings.etherscan_api_key,
        Chain.TRON: settings.trongrid_api_key,
    }

    chains: list[ChainInfo] = []
    for chain in Chain:
        display_name, native_asset, providers = CHAIN_DISPLAY[chain]
        is_mvp = chain in MVP_CHAINS

        if not is_mvp:
            # Roadmap chains report no coverage rather than a zero that looks like a gap in
            # an otherwise supported chain (DPRD sec.11 roadmap).
            chains.append(
                ChainInfo(
                    chain=chain,
                    display_name=display_name,
                    native_asset=native_asset,
                    status=ChainStatus.ROADMAP,
                    adapter_provenance=None,
                    providers=list(providers),
                    coverage=None,
                )
            )
            continue

        has_key = bool(provider_keys.get(chain))
        chains.append(
            ChainInfo(
                chain=chain,
                display_name=display_name,
                native_asset=native_asset,
                status=ChainStatus.SUPPORTED,
                # Without a key the adapter can only serve clearly-labelled demo data; say
                # so here so the UI never implies a live pull (brief: never present mock
                # data as real blockchain data).
                adapter_provenance="live_api" if has_key else "mock_demo",
                providers=list(providers),
                coverage=build_coverage(
                    coverage_by_chain.get(chain.value),
                    version=version,
                    stale_days=settings.stale_label_days,
                ),
            )
        )

    return ChainsResponse(chains=chains, stale_label_days_threshold=settings.stale_label_days)


def _sources(manifest: dict[str, Any] | None) -> list[DatasetSourceEntry]:
    entries = (manifest or {}).get("imported_sources") or []
    return [
        DatasetSourceEntry(
            name=entry.get("name", ""),
            kind=entry.get("kind", ""),
            url=entry.get("url", ""),
            file=entry.get("file", ""),
            sha256=entry.get("sha256", ""),
            tier=entry.get("tier", ""),
            licence=entry.get("licence", ""),
            retrieved=entry.get("retrieved", ""),
        )
        for entry in entries
    ]


@router.get(
    "/labels/versions",
    response_model=DatasetVersionsResponse,
    summary="Label dataset versions with their integrity reports",
)
async def list_versions(session: DbSession) -> DatasetVersionsResponse:
    stale_days = get_settings().stale_label_days
    versions = await labels_repo.list_dataset_versions(session)

    summaries: list[DatasetVersionSummary] = []
    for version in versions:
        age = labels_repo.label_age_days(version.imported_at)
        report = version.integrity_report or {}
        summaries.append(
            DatasetVersionSummary(
                id=str(version.id),
                version=version.version,
                imported_at=version.imported_at,
                age_days=age,
                is_stale=age > stale_days,
                vasp_address_count=version.vasp_address_count,
                risk_entity_count=version.risk_entity_count,
                sources=_sources(version.source_manifest),
                skipped_sources=list((version.source_manifest or {}).get("skipped_sources", [])),
                integrity_is_clean=report.get("is_clean"),
                integrity_warning_count=report.get("warning_count"),
            )
        )

    return DatasetVersionsResponse(
        versions=summaries,
        current_version=summaries[0].version if summaries else None,
    )
