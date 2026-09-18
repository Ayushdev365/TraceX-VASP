"""Label importer: provenance enforcement, atomicity, and the integrity scan.

The rejection tests matter more than the happy path. The product's honesty rests on the
claim that an uncited or unverifiable label *cannot* enter the database, so each of these
tests pins one way that could otherwise leak.
"""

from __future__ import annotations

import textwrap
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import LabelDatasetVersion, RiskEntity, Vasp, VaspAddress
from app.database.seeds import integrity
from app.database.seeds.demo_fixtures import (
    SOURCE_NAME,
    SOURCE_URL,
    derive_address,
    write_fixtures,
)
from app.database.seeds.import_labels import ImportError_, import_labels
from app.database.seeds.manifest import ManifestError, load_manifest
from app.schemas.common import Chain, LabelTier

VASP_HEADER = "vasp_slug,vasp_name,vasp_kind,chain,address,verification_status,verified_at\n"


def write_manifest(directory: Path, body: str, *, version: str = "test-1") -> Path:
    path = directory / "manifest.yaml"
    path.write_text(f"version: {version!r}\nsources:\n{textwrap.indent(body, '  ')}", "utf-8")
    return path


def vasp_source(file_name: str, *, tier: str = "community_verified") -> str:
    return textwrap.dedent(f"""\
        - name: "Test source"
          kind: vasp_addresses
          url: "https://example.org/labels"
          file: {file_name}
          tier: {tier}
          licence: "test"
          retrieved: 2026-09-18
        """)


class TestManifestValidation:
    def test_a_source_missing_its_url_is_refused(self, tmp_path: Path) -> None:
        (tmp_path / "labels.csv").write_text(VASP_HEADER, "utf-8")
        manifest = write_manifest(
            tmp_path,
            textwrap.dedent("""\
                - name: "No URL source"
                  kind: vasp_addresses
                  file: labels.csv
                  tier: community_verified
                  licence: "test"
                  retrieved: 2026-09-18
                """),
        )
        with pytest.raises(ManifestError, match="url"):
            load_manifest(manifest)

    def test_the_error_explains_why_provenance_is_mandatory(self, tmp_path: Path) -> None:
        (tmp_path / "labels.csv").write_text(VASP_HEADER, "utf-8")
        manifest = write_manifest(
            tmp_path,
            textwrap.dedent("""\
                - name: "Partial source"
                  kind: vasp_addresses
                  file: labels.csv
                  tier: community_verified
                  retrieved: 2026-09-18
                """),
        )
        with pytest.raises(ManifestError, match="uncited label cannot be imported"):
            load_manifest(manifest)

    def test_a_missing_version_is_refused(self, tmp_path: Path) -> None:
        (tmp_path / "labels.csv").write_text(VASP_HEADER, "utf-8")
        path = tmp_path / "manifest.yaml"
        path.write_text("sources: []\n", "utf-8")
        with pytest.raises(ManifestError, match="version"):
            load_manifest(path)

    def test_a_declared_file_that_does_not_exist_is_refused(self, tmp_path: Path) -> None:
        manifest = write_manifest(tmp_path, vasp_source("absent.csv"))
        with pytest.raises(ManifestError, match="not found"):
            load_manifest(manifest)

    def test_a_non_citable_url_is_refused(self, tmp_path: Path) -> None:
        (tmp_path / "labels.csv").write_text(VASP_HEADER, "utf-8")
        manifest = write_manifest(
            tmp_path,
            textwrap.dedent("""\
                - name: "Hearsay"
                  kind: vasp_addresses
                  url: "someone told me"
                  file: labels.csv
                  tier: community_verified
                  licence: "test"
                  retrieved: 2026-09-18
                """),
        )
        with pytest.raises(ManifestError, match="citable"):
            load_manifest(manifest)


class TestRowValidation:
    async def _import(self, session: AsyncSession, tmp_path: Path, rows: str) -> None:
        (tmp_path / "labels.csv").write_text(VASP_HEADER + rows, "utf-8")
        manifest = load_manifest(write_manifest(tmp_path, vasp_source("labels.csv")))
        await import_labels(session, manifest, allow_demo=False)

    async def test_an_invalid_address_fails_the_import(
        self, db_session: AsyncSession, tmp_path: Path
    ) -> None:
        with pytest.raises(ImportError_, match="invalid ethereum address"):
            await self._import(
                db_session, tmp_path, "acme,Acme,exchange,ethereum,0xnothex,unverified,\n"
            )

    async def test_verified_without_a_date_fails_the_import(
        self, db_session: AsyncSession, tmp_path: Path
    ) -> None:
        address = derive_address("ethereum", "test/1")
        with pytest.raises(ImportError_, match="cannot claim verification without a date"):
            await self._import(
                db_session, tmp_path, f"acme,Acme,exchange,ethereum,{address},verified,\n"
            )

    async def test_a_wrong_chain_address_fails_the_import(
        self, db_session: AsyncSession, tmp_path: Path
    ) -> None:
        tron_address = derive_address("tron", "test/1")
        with pytest.raises(ImportError_, match="invalid ethereum address"):
            await self._import(
                db_session, tmp_path, f"acme,Acme,exchange,ethereum,{tron_address},unverified,\n"
            )

    async def test_an_unknown_chain_fails_the_import(
        self, db_session: AsyncSession, tmp_path: Path
    ) -> None:
        with pytest.raises(ImportError_, match="unknown chain"):
            await self._import(
                db_session, tmp_path, "acme,Acme,exchange,dogecoin,Dxyz,unverified,\n"
            )

    async def test_an_unrecognised_column_fails_the_import(
        self, db_session: AsyncSession, tmp_path: Path
    ) -> None:
        (tmp_path / "labels.csv").write_text(
            "vasp_slug,vasp_name,vasp_kind,chain,address,secret_backdoor\n", "utf-8"
        )
        manifest = load_manifest(write_manifest(tmp_path, vasp_source("labels.csv")))
        with pytest.raises(ImportError_, match="unrecognised column"):
            await import_labels(db_session, manifest, allow_demo=False)

    async def test_the_failing_line_number_is_named(
        self, db_session: AsyncSession, tmp_path: Path
    ) -> None:
        good = derive_address("ethereum", "test/good")
        rows = (
            f"acme,Acme,exchange,ethereum,{good},unverified,\n"
            "acme,Acme,exchange,ethereum,0xbad,unverified,\n"
        )
        with pytest.raises(ImportError_, match="labels.csv:3"):
            await self._import(db_session, tmp_path, rows)

    async def test_nothing_is_written_when_a_row_fails(
        self, db_session: AsyncSession, tmp_path: Path
    ) -> None:
        """Atomicity: a partial import would leave the version claiming rows it lacks."""
        good = derive_address("ethereum", "test/good")
        rows = (
            f"acme,Acme,exchange,ethereum,{good},unverified,\n"
            "acme,Acme,exchange,ethereum,0xbad,unverified,\n"
        )
        with pytest.raises(ImportError_):
            await self._import(db_session, tmp_path, rows)
        await db_session.rollback()

        assert await db_session.scalar(select(func.count()).select_from(VaspAddress)) == 0
        assert await db_session.scalar(select(func.count()).select_from(Vasp)) == 0
        assert await db_session.scalar(select(func.count()).select_from(LabelDatasetVersion)) == 0


class TestDemoGating:
    def _demo_manifest(self, tmp_path: Path) -> Path:
        write_fixtures(tmp_path / "demo")
        # Uses the production source name/URL constants so the test cannot pass with a
        # friendlier label than the real import would apply.
        return write_manifest(
            tmp_path,
            textwrap.dedent(f"""\
                - name: "{SOURCE_NAME}"
                  kind: vasp_addresses
                  url: "{SOURCE_URL}"
                  file: demo/demo_vasp_addresses.csv
                  tier: demo_unverified
                  licence: "generated"
                  retrieved: 2026-09-18
                - name: "{SOURCE_NAME}"
                  kind: risk_entities
                  url: "{SOURCE_URL}"
                  file: demo/demo_risk_entities.csv
                  tier: demo_unverified
                  licence: "generated"
                  retrieved: 2026-09-18
                """),
        )

    async def test_demo_sources_are_skipped_by_default(
        self, db_session: AsyncSession, tmp_path: Path
    ) -> None:
        manifest = load_manifest(self._demo_manifest(tmp_path))
        result = await import_labels(db_session, manifest, allow_demo=False)

        assert result.vasp_addresses_inserted == 0
        assert result.risk_entities_inserted == 0
        assert result.skipped_demo_sources

    async def test_demo_sources_import_when_explicitly_allowed(
        self, db_session: AsyncSession, tmp_path: Path
    ) -> None:
        manifest = load_manifest(self._demo_manifest(tmp_path))
        result = await import_labels(db_session, manifest, allow_demo=True)

        assert result.vasp_addresses_inserted == 10
        assert result.risk_entities_inserted == 6
        assert result.vasps_created == 3

        rows = (await db_session.execute(select(VaspAddress))).scalars().all()
        # Every demo row must land at the lowest tier and stay unverified — the tier the
        # attribution engine refuses to treat as sufficient evidence.
        assert {row.source_tier for row in rows} == {LabelTier.DEMO_UNVERIFIED.value}
        assert {row.verification_status for row in rows} == {"unverified"}
        assert all(row.source_url for row in rows)
        assert all("NOT REAL DATA" in row.source for row in rows)

    async def test_a_demo_source_cannot_declare_itself_verified(
        self, db_session: AsyncSession, tmp_path: Path
    ) -> None:
        address = derive_address("ethereum", "test/1")
        (tmp_path / "labels.csv").write_text(
            VASP_HEADER + f"acme,Acme,exchange,ethereum,{address},verified,2026-01-01T00:00:00Z\n",
            "utf-8",
        )
        manifest = load_manifest(
            write_manifest(tmp_path, vasp_source("labels.csv", tier="demo_unverified"))
        )
        with pytest.raises(ImportError_, match="demo_unverified source cannot declare"):
            await import_labels(db_session, manifest, allow_demo=True)


class TestSuccessfulImport:
    async def test_provenance_and_version_are_recorded(
        self, db_session: AsyncSession, tmp_path: Path
    ) -> None:
        address = derive_address("ethereum", "test/1")
        (tmp_path / "labels.csv").write_text(
            VASP_HEADER
            + f"acme,Acme Exchange,exchange,ethereum,{address},verified,2026-09-01T00:00:00Z\n",
            "utf-8",
        )
        manifest = load_manifest(write_manifest(tmp_path, vasp_source("labels.csv")))

        result = await import_labels(db_session, manifest, allow_demo=False)
        assert result.vasp_addresses_inserted == 1

        row = (await db_session.execute(select(VaspAddress))).scalar_one()
        assert row.source == "Test source"
        assert row.source_url == "https://example.org/labels"
        assert row.source_tier == LabelTier.COMMUNITY_VERIFIED.value
        assert row.verified_at is not None
        # Default reliability comes from the tier, not from a hardcoded constant.
        assert float(row.reliability) == pytest.approx(0.75)

        version = (await db_session.execute(select(LabelDatasetVersion))).scalar_one()
        assert version.version == "test-1"
        assert version.vasp_address_count == 1
        source_entry = version.source_manifest["imported_sources"][0]
        # The file hash lets a reviewer confirm which exact bytes produced these labels.
        assert len(source_entry["sha256"]) == 64
        assert source_entry["licence"] == "test"

    async def test_addresses_are_stored_canonically(
        self, db_session: AsyncSession, tmp_path: Path
    ) -> None:
        """A non-canonical stored label would never match during traversal."""
        checksummed = "0x5aAeb6053F3E94C9b9A09f33669435E7Ef1BeAed"
        (tmp_path / "labels.csv").write_text(
            VASP_HEADER + f"acme,Acme,exchange,ethereum,{checksummed},unverified,\n", "utf-8"
        )
        manifest = load_manifest(write_manifest(tmp_path, vasp_source("labels.csv")))
        await import_labels(db_session, manifest, allow_demo=False)

        row = (await db_session.execute(select(VaspAddress))).scalar_one()
        assert row.address == checksummed.lower()

    async def test_re_importing_a_version_is_refused(
        self, db_session: AsyncSession, tmp_path: Path
    ) -> None:
        address = derive_address("ethereum", "test/1")
        (tmp_path / "labels.csv").write_text(
            VASP_HEADER + f"acme,Acme,exchange,ethereum,{address},unverified,\n", "utf-8"
        )
        manifest = load_manifest(write_manifest(tmp_path, vasp_source("labels.csv")))

        await import_labels(db_session, manifest, allow_demo=False)
        await db_session.commit()

        with pytest.raises(ImportError_, match="already exists"):
            await import_labels(db_session, manifest, allow_demo=False)

    async def test_risk_entities_inherit_the_default_severity(
        self, db_session: AsyncSession, tmp_path: Path
    ) -> None:
        address = derive_address("ethereum", "mixer/1")
        (tmp_path / "risk.csv").write_text(
            f"chain,address,entity_kind\nethereum,{address},mixer\n", "utf-8"
        )
        manifest = load_manifest(
            write_manifest(
                tmp_path,
                textwrap.dedent("""\
                    - name: "Sanctions source"
                      kind: risk_entities
                      url: "https://example.org/sdn"
                      file: risk.csv
                      tier: sanctions_list
                      licence: "public domain"
                      retrieved: 2026-09-18
                      default_severity: high
                    """),
            )
        )
        await import_labels(db_session, manifest, allow_demo=False)

        row = (await db_session.execute(select(RiskEntity))).scalar_one()
        assert row.severity == "high"
        assert row.source_tier == LabelTier.SANCTIONS_LIST.value


class TestIntegrityScan:
    async def _seed_version(self, session: AsyncSession) -> LabelDatasetVersion:
        version = LabelDatasetVersion(version="scan-1", source_manifest={})
        session.add(version)
        await session.flush()
        return version

    async def _add_label(
        self,
        session: AsyncSession,
        version: LabelDatasetVersion,
        *,
        slug: str,
        address: str,
        source: str,
        chain: Chain = Chain.ETHEREUM,
    ) -> None:
        vasp = (await session.execute(select(Vasp).where(Vasp.slug == slug))).scalar_one_or_none()
        if vasp is None:
            vasp = Vasp(slug=slug, name=slug.title(), kind="exchange")
            session.add(vasp)
            await session.flush()
        session.add(
            VaspAddress(
                vasp_id=vasp.id,
                chain=chain.value,
                address=address,
                source=source,
                source_url="https://example.org",
                source_tier=LabelTier.COMMUNITY_UNVERIFIED.value,
                verification_status="unverified",
                reliability=0.55,
                dataset_version_id=version.id,
                last_updated_at=datetime.now(UTC),
            )
        )
        await session.flush()

    async def test_a_clean_dataset_reports_clean(self, db_session: AsyncSession) -> None:
        version = await self._seed_version(db_session)
        await self._add_label(
            db_session,
            version,
            slug="acme",
            address=derive_address("ethereum", "a").lower(),
            source="Source A",
        )

        report = await integrity.scan(db_session)
        assert report.is_clean
        assert report.warning_count == 0
        assert report.chains_covered == ["ethereum"]

    async def test_conflicting_owners_are_flagged_not_resolved(
        self, db_session: AsyncSession
    ) -> None:
        """DPRD sec.21: never silently pick one of two disagreeing sources."""
        version = await self._seed_version(db_session)
        shared = derive_address("ethereum", "contested").lower()
        await self._add_label(db_session, version, slug="acme", address=shared, source="Source A")
        await self._add_label(db_session, version, slug="globex", address=shared, source="Source B")

        report = await integrity.scan(db_session)
        # A conflict is a reviewable finding, not an import failure.
        assert report.is_clean
        assert len(report.conflicting_labels) == 1

        conflict = report.conflicting_labels[0]
        assert conflict["address"] == shared
        assert conflict["claim_count"] == 2
        assert "no claim was auto-selected" in conflict["resolution"]
        # Both rows survive, so an investigator sees both.
        assert await db_session.scalar(select(func.count()).select_from(VaspAddress)) == 2

    async def test_a_non_canonical_stored_address_is_a_failure(
        self, db_session: AsyncSession
    ) -> None:
        """This would silently never match, so it must block the dataset."""
        version = await self._seed_version(db_session)
        await self._add_label(
            db_session,
            version,
            slug="acme",
            address="0x5aAeb6053F3E94C9b9A09f33669435E7Ef1BeAed",  # checksummed, not canonical
            source="Source A",
        )

        report = await integrity.scan(db_session)
        assert not report.is_clean
        assert report.malformed_addresses
        assert "canonical" in report.malformed_addresses[0]["reason"]

    async def test_an_address_labelled_as_both_vasp_and_mixer_is_flagged(
        self, db_session: AsyncSession
    ) -> None:
        version = await self._seed_version(db_session)
        shared = derive_address("ethereum", "both").lower()
        await self._add_label(db_session, version, slug="acme", address=shared, source="Source A")
        db_session.add(
            RiskEntity(
                chain="ethereum",
                address=shared,
                entity_kind="mixer",
                severity="high",
                source="Sanctions",
                source_url="https://example.org/sdn",
                source_tier=LabelTier.SANCTIONS_LIST.value,
                verification_status="verified",
                dataset_version_id=version.id,
                last_updated_at=datetime.now(UTC),
            )
        )
        await db_session.flush()

        report = await integrity.scan(db_session)
        assert len(report.vasp_and_risk_overlap) == 1
        # The risk indicator must keep firing; a VASP label does not clear it.
        assert "risk indicator still fires" in report.vasp_and_risk_overlap[0]["resolution"]


class TestDemoFixtureGenerator:
    def test_derivation_is_deterministic(self) -> None:
        assert derive_address("ethereum", "seed/1") == derive_address("ethereum", "seed/1")
        assert derive_address("ethereum", "seed/1") != derive_address("ethereum", "seed/2")

    def test_derived_addresses_are_valid_for_their_chain(self) -> None:
        from app.blockchain.addresses import validate_address

        assert validate_address(derive_address("ethereum", "x"), Chain.ETHEREUM).valid
        assert validate_address(derive_address("tron", "x"), Chain.TRON).valid

    def test_demo_vasp_names_are_marked_as_demo(self) -> None:
        """No fabricated address may ever be attached to a real company's name."""
        from app.database.seeds.demo_fixtures import DEMO_RISK_ENTITIES, DEMO_VASPS

        assert all(vasp.name.startswith("DEMO — ") for vasp in DEMO_VASPS)
        assert all(vasp.slug.startswith("demo-") for vasp in DEMO_VASPS)
        assert all(entity[2].startswith("DEMO — ") for entity in DEMO_RISK_ENTITIES)
