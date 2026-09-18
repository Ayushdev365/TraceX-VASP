"""Label dataset integrity scan.

Runs after every import and writes its findings to
``label_dataset_versions.integrity_report``. This is the DPRD sec.13 dataset gate — a chain's
labels are not "production ready" until this scan is clean — and the DPRD sec.35 weekly QC
check.

The scan never mutates data. In particular it does not resolve conflicts: when two sources
disagree about who owns an address, both rows stay and the conflict is reported, because
silently picking one is exactly the behaviour DPRD sec.21 forbids.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.blockchain.addresses import validate_address
from app.database.models import RiskEntity, VaspAddress
from app.schemas.common import Chain


@dataclass(slots=True)
class IntegrityReport:
    """Findings from one scan. ``is_clean`` gates the dataset's production readiness."""

    vasp_address_count: int = 0
    risk_entity_count: int = 0
    duplicate_labels: list[dict[str, Any]] = field(default_factory=list)
    conflicting_labels: list[dict[str, Any]] = field(default_factory=list)
    vasp_and_risk_overlap: list[dict[str, Any]] = field(default_factory=list)
    malformed_addresses: list[dict[str, Any]] = field(default_factory=list)
    unverified_claiming_verified: list[dict[str, Any]] = field(default_factory=list)
    chains_covered: list[str] = field(default_factory=list)

    @property
    def is_clean(self) -> bool:
        """Conflicts are *not* a failure — they are a reviewable finding (DPRD sec.21).

        Malformed addresses and false verification claims are failures: the first breaks
        matching silently, the second breaks the product's honesty guarantee.
        """
        return not self.malformed_addresses and not self.unverified_claiming_verified

    @property
    def warning_count(self) -> int:
        return (
            len(self.duplicate_labels)
            + len(self.conflicting_labels)
            + len(self.vasp_and_risk_overlap)
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "is_clean": self.is_clean,
            "warning_count": self.warning_count,
            "vasp_address_count": self.vasp_address_count,
            "risk_entity_count": self.risk_entity_count,
            "chains_covered": self.chains_covered,
            "findings": {
                "duplicate_labels": self.duplicate_labels,
                "conflicting_labels": self.conflicting_labels,
                "vasp_and_risk_overlap": self.vasp_and_risk_overlap,
                "malformed_addresses": self.malformed_addresses,
                "unverified_claiming_verified": self.unverified_claiming_verified,
            },
        }


async def scan(session: AsyncSession) -> IntegrityReport:
    """Scan every active label and risk entity in the database."""
    report = IntegrityReport()

    vasp_rows = (
        (await session.execute(select(VaspAddress).where(VaspAddress.is_active.is_(True))))
        .scalars()
        .all()
    )
    risk_rows = (
        (await session.execute(select(RiskEntity).where(RiskEntity.is_active.is_(True))))
        .scalars()
        .all()
    )

    report.vasp_address_count = len(vasp_rows)
    report.risk_entity_count = len(risk_rows)
    report.chains_covered = sorted(
        {row.chain for row in vasp_rows} | {row.chain for row in risk_rows}
    )

    # ─── duplicates: identical claim asserted twice by the same source ───
    seen: dict[tuple[str, str, Any, str], int] = defaultdict(int)
    for row in vasp_rows:
        seen[(row.chain, row.address, row.vasp_id, row.source)] += 1
    report.duplicate_labels = [
        {
            "chain": chain,
            "address": address,
            "source": source,
            "occurrences": count,
        }
        for (chain, address, _vasp_id, source), count in seen.items()
        if count > 1
    ]

    # ─── conflicts: one address, two different owners ───
    by_address: dict[tuple[str, str], list[VaspAddress]] = defaultdict(list)
    for row in vasp_rows:
        by_address[(row.chain, row.address)].append(row)
    for (chain, address), rows in by_address.items():
        owners = {row.vasp_id for row in rows}
        if len(owners) > 1:
            report.conflicting_labels.append(
                {
                    "chain": chain,
                    "address": address,
                    "claim_count": len(rows),
                    "claims": [
                        {
                            "vasp_id": str(row.vasp_id),
                            "source": row.source,
                            "source_url": row.source_url,
                            "source_tier": row.source_tier,
                        }
                        for row in rows
                    ],
                    "resolution": "flagged for manual review; no claim was auto-selected",
                }
            )

    # ─── an address labelled both as a VASP and as a mixer/bridge ───
    risk_index: dict[tuple[str, str], list[RiskEntity]] = defaultdict(list)
    for risk_row in risk_rows:
        risk_index[(risk_row.chain, risk_row.address)].append(risk_row)
    for key, vasp_claims in by_address.items():
        if key in risk_index:
            chain, address = key
            report.vasp_and_risk_overlap.append(
                {
                    "chain": chain,
                    "address": address,
                    "vasp_sources": [row.source for row in vasp_claims],
                    "risk_kinds": [row.entity_kind for row in risk_index[key]],
                    "resolution": "both retained; the risk indicator still fires on this path",
                }
            )

    # ─── malformed addresses: would silently never match (DPRD sec.17) ───
    labelled: list[VaspAddress | RiskEntity] = [*vasp_rows, *risk_rows]
    for labelled_row in labelled:
        try:
            chain = Chain(labelled_row.chain)
        except ValueError:
            report.malformed_addresses.append(
                {
                    "address": labelled_row.address,
                    "chain": labelled_row.chain,
                    "reason": "unknown chain",
                }
            )
            continue
        result = validate_address(labelled_row.address, chain)
        if not result.valid:
            report.malformed_addresses.append(
                {
                    "address": labelled_row.address,
                    "chain": labelled_row.chain,
                    "reason": result.error_code.value if result.error_code else "invalid",
                }
            )
        elif result.canonical_address != labelled_row.address:
            report.malformed_addresses.append(
                {
                    "address": labelled_row.address,
                    "chain": labelled_row.chain,
                    "reason": "not stored in canonical form; matching would miss it",
                    "canonical": result.canonical_address,
                }
            )

    # ─── verification claims that the data cannot support ───
    for row in vasp_rows:
        if row.verification_status == "verified" and row.verified_at is None:
            report.unverified_claiming_verified.append(
                {"address": row.address, "chain": row.chain, "source": row.source}
            )

    return report
