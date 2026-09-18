"""Provenance-enforcing label importer.

    python -m app.database.seeds.import_labels --manifest ../data/labels/manifest.yaml
    python -m app.database.seeds.import_labels --manifest ... --dry-run
    python -m app.database.seeds.import_labels --manifest ... --allow-demo

Design rules, each traceable to a requirement:

* **Atomic.** One manifest becomes one ``label_dataset_versions`` row and one transaction.
  A partial import would leave the dataset version claiming rows it does not have, breaking
  the reproducibility guarantee (DPRD sec.15).
* **Fail the whole import on any invalid row.** Skipping bad rows quietly is how a dataset
  rots; the operator is told exactly which line failed and why.
* **No uncited labels.** ``source`` and ``source_url`` come from the manifest, never from a
  default, so there is no code path that inserts a label of unknown origin.
* **Demo labels are opt-in.** ``demo_unverified`` sources are skipped unless
  ``ALLOW_DEMO_LABELS=true`` or ``--allow-demo`` is passed, and are refused outright in
  production.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.blockchain.addresses import validate_address
from app.config import get_settings
from app.core.logging import configure_logging, get_logger
from app.database.models import LabelDatasetVersion, RiskEntity, Vasp, VaspAddress
from app.database.seeds import integrity
from app.database.seeds.manifest import (
    LabelManifest,
    LabelSource,
    ManifestError,
    SourceKind,
    load_manifest,
)
from app.database.session import get_sessionmaker
from app.schemas.common import (
    TIER_RELIABILITY,
    AddressType,
    Chain,
    LabelTier,
    RiskEntityKind,
    Severity,
    VaspKind,
    VerificationStatus,
)

logger = get_logger(__name__)

DRY_RUN_SUFFIX = " (DRY RUN — nothing written)"

VASP_COLUMNS = {
    "required": ("vasp_slug", "vasp_name", "vasp_kind", "chain", "address"),
    "optional": (
        "jurisdiction",
        "website",
        "nodal_officer_channel",
        "legal_entity",
        "is_fiu_ind_registered",
        "address_type",
        "verification_status",
        "verified_by",
        "verified_at",
        "reliability",
        "notes",
    ),
}
RISK_COLUMNS = {
    "required": ("chain", "address", "entity_kind"),
    "optional": ("entity_name", "severity", "verification_status", "notes"),
}


class ImportError_(Exception):
    """Raised with a message naming the file and line that caused the failure."""


@dataclass(slots=True)
class ImportResult:
    version: str
    dry_run: bool
    vasps_created: int = 0
    vasp_addresses_inserted: int = 0
    risk_entities_inserted: int = 0
    skipped_demo_sources: list[str] = field(default_factory=list)
    integrity_report: dict[str, Any] | None = None

    def summary(self) -> str:
        lines = [
            f"dataset version : {self.version}{DRY_RUN_SUFFIX if self.dry_run else ''}",
            f"VASPs           : {self.vasps_created} created/updated",
            f"VASP addresses  : {self.vasp_addresses_inserted}",
            f"risk entities   : {self.risk_entities_inserted}",
        ]
        if self.skipped_demo_sources:
            lines.append(
                "skipped (demo)  : "
                + ", ".join(self.skipped_demo_sources)
                + "  [set ALLOW_DEMO_LABELS=true or pass --allow-demo to include]"
            )
        if self.integrity_report:
            report = self.integrity_report
            lines.append(
                f"integrity       : {'CLEAN' if report['is_clean'] else 'FAILED'}, "
                f"{report['warning_count']} warning(s)"
            )
            for name, findings in report["findings"].items():
                if findings:
                    lines.append(f"  - {name}: {len(findings)}")
        return "\n".join(lines)


def _require(value: str | None, column: str, source: LabelSource, line: int) -> str:
    text = (value or "").strip()
    if not text:
        raise ImportError_(
            f"{source.path.name}:{line} — column '{column}' is required and was empty"
        )
    return text


def _parse_chain(raw: str, source: LabelSource, line: int) -> Chain:
    try:
        return Chain(raw.strip().lower())
    except ValueError as exc:
        raise ImportError_(
            f"{source.path.name}:{line} — unknown chain {raw!r}; expected one of "
            f"{', '.join(c.value for c in Chain)}"
        ) from exc


def _parse_address(raw: str, chain: Chain, source: LabelSource, line: int) -> tuple[str, str]:
    """Return ``(canonical, display)``, failing the import if the address is invalid.

    An invalid or non-canonical label address would never match during traversal, producing
    a silent false negative — the DPRD sec.17 format-mismatch failure mode.
    """
    result = validate_address(raw.strip(), chain)
    if not result.valid or result.canonical_address is None:
        raise ImportError_(
            f"{source.path.name}:{line} — invalid {chain.value} address {raw!r}: "
            f"{result.error_message}"
        )
    return result.canonical_address, result.display_address or result.canonical_address


def _parse_enum(
    raw: str | None,
    enum: type,
    column: str,
    source: LabelSource,
    line: int,
    *,
    default: Any = None,
) -> Any:
    text = (raw or "").strip().lower()
    if not text:
        if default is not None:
            return default
        raise ImportError_(f"{source.path.name}:{line} — column '{column}' is required")
    try:
        return enum(text)
    except ValueError as exc:
        allowed = ", ".join(m.value for m in enum)  # type: ignore[attr-defined]
        raise ImportError_(
            f"{source.path.name}:{line} — column '{column}' has {raw!r}; expected one of {allowed}"
        ) from exc


def _parse_verified_at(
    raw: str | None, status: VerificationStatus, source: LabelSource, line: int
) -> datetime | None:
    text = (raw or "").strip()
    if not text:
        if status is VerificationStatus.VERIFIED:
            raise ImportError_(
                f"{source.path.name}:{line} — verification_status is 'verified' but "
                f"verified_at is empty. A label cannot claim verification without a date."
            )
        return None
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise ImportError_(
            f"{source.path.name}:{line} — verified_at {raw!r} is not an ISO-8601 date"
        ) from exc
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _read_rows(source: LabelSource, expected: dict[str, tuple[str, ...]]) -> list[dict[str, str]]:
    with source.path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            raise ImportError_(f"{source.path.name} has no header row")
        headers = {name.strip() for name in reader.fieldnames}
        missing = [column for column in expected["required"] if column not in headers]
        if missing:
            raise ImportError_(
                f"{source.path.name} is missing required column(s): {', '.join(missing)}"
            )
        unknown = headers - set(expected["required"]) - set(expected["optional"])
        if unknown:
            raise ImportError_(
                f"{source.path.name} has unrecognised column(s): {', '.join(sorted(unknown))}"
            )
        return [row for row in reader if any((value or "").strip() for value in row.values())]


async def _upsert_vasp(
    session: AsyncSession, row: dict[str, str], source: LabelSource, line: int
) -> tuple[Vasp, bool]:
    slug = _require(row.get("vasp_slug"), "vasp_slug", source, line).lower()
    existing = (await session.execute(select(Vasp).where(Vasp.slug == slug))).scalar_one_or_none()

    kind = _parse_enum(row.get("vasp_kind"), VaspKind, "vasp_kind", source, line)
    name = _require(row.get("vasp_name"), "vasp_name", source, line)

    fiu_raw = (row.get("is_fiu_ind_registered") or "").strip().lower()
    # Null means unknown. Only an explicit true/false is recorded, because whether an LEA can
    # route a request to this VASP is a factual claim requiring a source.
    is_fiu = {"true": True, "yes": True, "false": False, "no": False}.get(fiu_raw)

    if existing is not None:
        existing.name = name
        existing.kind = kind.value
        if row.get("jurisdiction"):
            existing.jurisdiction = row["jurisdiction"].strip().upper()[:8]
        if row.get("website"):
            existing.website = row["website"].strip()
        if row.get("nodal_officer_channel"):
            existing.nodal_officer_channel = row["nodal_officer_channel"].strip()
        if row.get("legal_entity"):
            existing.legal_entity = row["legal_entity"].strip()
        if is_fiu is not None:
            existing.is_fiu_ind_registered = is_fiu
        return existing, False

    vasp = Vasp(
        slug=slug,
        name=name,
        kind=kind.value,
        legal_entity=(row.get("legal_entity") or "").strip() or None,
        jurisdiction=(row.get("jurisdiction") or "").strip().upper()[:8] or None,
        is_fiu_ind_registered=is_fiu,
        website=(row.get("website") or "").strip() or None,
        nodal_officer_channel=(row.get("nodal_officer_channel") or "").strip() or None,
    )
    session.add(vasp)
    await session.flush()
    return vasp, True


async def _import_vasp_source(
    session: AsyncSession,
    source: LabelSource,
    version: LabelDatasetVersion,
    result: ImportResult,
) -> None:
    rows = _read_rows(source, VASP_COLUMNS)
    now = datetime.now(UTC)

    for offset, row in enumerate(rows):
        line = offset + 2  # +1 for the header, +1 for 1-based numbering
        chain = _parse_chain(_require(row.get("chain"), "chain", source, line), source, line)
        canonical, _display = _parse_address(
            _require(row.get("address"), "address", source, line), chain, source, line
        )

        vasp, created = await _upsert_vasp(session, row, source, line)
        if created:
            result.vasps_created += 1

        status: VerificationStatus = _parse_enum(
            row.get("verification_status"),
            VerificationStatus,
            "verification_status",
            source,
            line,
            default=VerificationStatus.UNVERIFIED,
        )
        # Mirrors the database CHECK: a demo label can only ever be 'unverified'.
        if source.tier is LabelTier.DEMO_UNVERIFIED and status is not VerificationStatus.UNVERIFIED:
            raise ImportError_(
                f"{source.path.name}:{line} — a demo_unverified source cannot declare "
                f"verification_status={status.value!r}"
            )

        address_type = (
            _parse_enum(row.get("address_type"), AddressType, "address_type", source, line)
            if (row.get("address_type") or "").strip()
            else None
        )

        reliability_raw = (row.get("reliability") or "").strip()
        reliability = (
            Decimal(reliability_raw)
            if reliability_raw
            else Decimal(str(TIER_RELIABILITY[source.tier]))
        )
        if not Decimal(0) <= reliability <= Decimal(1):
            raise ImportError_(
                f"{source.path.name}:{line} — reliability {reliability} is outside 0.00–1.00"
            )

        session.add(
            VaspAddress(
                vasp_id=vasp.id,
                chain=chain.value,
                address=canonical,
                address_type=address_type.value if address_type else None,
                source=source.name,
                source_url=source.url,
                source_tier=source.tier.value,
                verification_status=status.value,
                verified_by=(row.get("verified_by") or "").strip() or None,
                verified_at=_parse_verified_at(row.get("verified_at"), status, source, line),
                reliability=reliability,
                notes=(row.get("notes") or "").strip() or None,
                dataset_version_id=version.id,
                last_updated_at=now,
                is_active=True,
            )
        )
        result.vasp_addresses_inserted += 1


async def _import_risk_source(
    session: AsyncSession,
    source: LabelSource,
    version: LabelDatasetVersion,
    result: ImportResult,
) -> None:
    rows = _read_rows(source, RISK_COLUMNS)
    now = datetime.now(UTC)

    for offset, row in enumerate(rows):
        line = offset + 2
        chain = _parse_chain(_require(row.get("chain"), "chain", source, line), source, line)
        canonical, _display = _parse_address(
            _require(row.get("address"), "address", source, line), chain, source, line
        )
        entity_kind: RiskEntityKind = _parse_enum(
            row.get("entity_kind"), RiskEntityKind, "entity_kind", source, line
        )
        severity: Severity = _parse_enum(
            row.get("severity"),
            Severity,
            "severity",
            source,
            line,
            default=source.default_severity or Severity.MEDIUM,
        )
        status: VerificationStatus = _parse_enum(
            row.get("verification_status"),
            VerificationStatus,
            "verification_status",
            source,
            line,
            default=VerificationStatus.UNVERIFIED,
        )

        session.add(
            RiskEntity(
                chain=chain.value,
                address=canonical,
                entity_kind=entity_kind.value,
                entity_name=(row.get("entity_name") or "").strip() or None,
                severity=severity.value,
                source=source.name,
                source_url=source.url,
                source_tier=source.tier.value,
                verification_status=status.value,
                dataset_version_id=version.id,
                notes=(row.get("notes") or "").strip() or None,
                last_updated_at=now,
                is_active=True,
            )
        )
        result.risk_entities_inserted += 1


async def import_labels(
    session: AsyncSession,
    manifest: LabelManifest,
    *,
    allow_demo: bool,
    dry_run: bool = False,
) -> ImportResult:
    """Import every source in ``manifest`` inside the caller's transaction."""
    result = ImportResult(version=manifest.version, dry_run=dry_run)

    sources = manifest.sources
    if not allow_demo:
        result.skipped_demo_sources = [s.name for s in manifest.demo_sources]
        sources = manifest.without_demo().sources

    existing = (
        await session.execute(
            select(LabelDatasetVersion).where(LabelDatasetVersion.version == manifest.version)
        )
    ).scalar_one_or_none()
    if existing is not None:
        raise ImportError_(
            f"dataset version {manifest.version!r} already exists. Bump 'version' in "
            f"{manifest.path.name} — versions are immutable so past traces stay reproducible."
        )

    version = LabelDatasetVersion(
        version=manifest.version,
        chain=None,
        source_manifest={
            "manifest_path": str(manifest.path),
            "imported_sources": [
                {
                    "name": s.name,
                    "kind": s.kind.value,
                    "url": s.url,
                    "file": s.path.name,
                    "sha256": s.sha256(),
                    "tier": s.tier.value,
                    "licence": s.licence,
                    "retrieved": s.retrieved.isoformat(),
                }
                for s in sources
            ],
            "skipped_sources": result.skipped_demo_sources,
        },
    )
    session.add(version)
    await session.flush()

    for source in sources:
        if source.kind is SourceKind.VASP_ADDRESSES:
            await _import_vasp_source(session, source, version, result)
        else:
            await _import_risk_source(session, source, version, result)

    version.vasp_address_count = result.vasp_addresses_inserted
    version.risk_entity_count = result.risk_entities_inserted

    await session.flush()
    report = await integrity.scan(session)
    version.integrity_report = report.to_dict()
    result.integrity_report = version.integrity_report

    if not report.is_clean:
        raise ImportError_(
            "integrity scan failed — import rolled back.\n"
            + "\n".join(
                f"  {name}: {len(findings)}"
                for name, findings in report.to_dict()["findings"].items()
                if findings
            )
        )

    return result


async def _main(argv: list[str] | None = None) -> int:
    default_manifest = (
        Path(__file__).resolve().parents[3] / ".." / "data" / "labels" / "manifest.yaml"
    ).resolve()

    parser = argparse.ArgumentParser(description="Import labelled VASP and risk addresses.")
    parser.add_argument("--manifest", type=Path, default=default_manifest)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="validate and scan, then roll back without writing",
    )
    parser.add_argument(
        "--allow-demo",
        action="store_true",
        help="include demo_unverified sources (refused when APP_ENV=production)",
    )
    args = parser.parse_args(argv)

    settings = get_settings()
    configure_logging(settings.log_level, secrets=(settings.database_url,))

    allow_demo = args.allow_demo or settings.allow_demo_labels
    if allow_demo and settings.is_production:
        print("refusing to import demo_unverified labels in production", file=sys.stderr)
        return 2

    try:
        manifest = load_manifest(args.manifest)
    except ManifestError as exc:
        print(f"manifest error: {exc}", file=sys.stderr)
        return 2

    async with get_sessionmaker()() as session:
        try:
            result = await import_labels(
                session, manifest, allow_demo=allow_demo, dry_run=args.dry_run
            )
        except ImportError_ as exc:
            await session.rollback()
            print(f"import failed — nothing was written.\n{exc}", file=sys.stderr)
            return 1

        if args.dry_run:
            await session.rollback()
        else:
            await session.commit()

    print(result.summary())
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
