"""VASP directory, address lookup and coverage endpoints."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import LabelDatasetVersion, Vasp, VaspAddress
from app.database.seeds.demo_fixtures import derive_address
from app.schemas.common import LabelTier

ETH_CHECKSUMMED = "0x5aAeb6053F3E94C9b9A09f33669435E7Ef1BeAed"
ETH_CANONICAL = ETH_CHECKSUMMED.lower()


def run_seed(client: TestClient, seeder: Callable[[AsyncSession], Awaitable[None]]) -> None:
    """Run a seeding coroutine against the client's own database.

    Uses the app's overridden session dependency so the test data lands in exactly the
    database the endpoints will read.
    """
    from app.deps import get_session

    override = client.app.dependency_overrides[get_session]  # type: ignore[attr-defined]

    async def _run() -> None:
        async for session in override():
            await seeder(session)
            await session.commit()
            break

    asyncio.run(_run())


async def seed_label(
    session: AsyncSession,
    *,
    slug: str = "acme-exchange",
    name: str = "Acme Exchange",
    address: str = ETH_CANONICAL,
    source: str = "Test source",
    tier: LabelTier = LabelTier.COMMUNITY_VERIFIED,
) -> Vasp:
    version = (await session.execute(select(LabelDatasetVersion).limit(1))).scalar_one_or_none()
    if version is None:
        row = LabelDatasetVersion(
            version="api-test-1",
            source_manifest={
                "imported_sources": [
                    {
                        "name": source,
                        "kind": "vasp_addresses",
                        "url": "https://example.org/labels",
                        "file": "labels.csv",
                        "sha256": "0" * 64,
                        "tier": tier.value,
                        "licence": "test",
                        "retrieved": "2026-09-18",
                    }
                ],
                "skipped_sources": [],
            },
            integrity_report={"is_clean": True, "warning_count": 0},
        )
        session.add(row)
        await session.flush()
        version_id = row.id
    else:
        version_id = version.id

    vasp = Vasp(slug=slug, name=name, kind="exchange", jurisdiction="SG")
    session.add(vasp)
    await session.flush()

    session.add(
        VaspAddress(
            vasp_id=vasp.id,
            chain="ethereum",
            address=address,
            address_type="deposit",
            source=source,
            source_url="https://example.org/labels",
            source_tier=tier.value,
            verification_status="unverified",
            reliability=0.75,
            dataset_version_id=version_id,
            last_updated_at=datetime.now(UTC),
        )
    )
    await session.flush()
    return vasp


@pytest.fixture
def seeded_client(client: TestClient) -> TestClient:
    """Client whose database already contains one labelled address."""

    async def _seed(session: AsyncSession) -> None:
        await seed_label(session)

    run_seed(client, _seed)
    return client


class TestChainsEndpoint:
    def test_mvp_chains_are_supported_and_roadmap_chains_are_not(
        self, client: TestClient, api_prefix: str
    ) -> None:
        body = client.get(f"{api_prefix}/meta/chains").json()
        by_chain = {entry["chain"]: entry for entry in body["chains"]}

        assert by_chain["ethereum"]["status"] == "supported"
        assert by_chain["tron"]["status"] == "supported"
        for roadmap in ("bitcoin", "bnb", "solana", "polygon"):
            assert by_chain[roadmap]["status"] == "roadmap"
            # Roadmap chains report no coverage rather than a misleading zero.
            assert by_chain[roadmap]["coverage"] is None

    def test_without_a_provider_key_the_adapter_declares_mock_provenance(
        self, client: TestClient, api_prefix: str
    ) -> None:
        """Never imply a live pull when no key is configured."""
        body = client.get(f"{api_prefix}/meta/chains").json()
        by_chain = {entry["chain"]: entry for entry in body["chains"]}
        assert by_chain["ethereum"]["adapter_provenance"] == "mock_demo"

    def test_an_empty_dataset_reports_no_coverage_honestly(
        self, client: TestClient, api_prefix: str
    ) -> None:
        body = client.get(f"{api_prefix}/meta/chains").json()
        coverage = next(c for c in body["chains"] if c["chain"] == "ethereum")["coverage"]

        assert coverage["coverage_level"] == "none"
        assert coverage["vasp_address_count"] == 0
        assert "not possible until the label dataset covers it" in coverage["coverage_notice"]

    def test_coverage_is_never_described_as_complete(
        self, seeded_client: TestClient, api_prefix: str
    ) -> None:
        body = seeded_client.get(f"{api_prefix}/meta/chains").json()
        coverage = next(c for c in body["chains"] if c["chain"] == "ethereum")["coverage"]

        assert coverage["coverage_level"] in {"limited", "partial"}
        assert coverage["vasp_address_count"] == 1
        # The crucial sentence: a non-match must never be read as "no VASP relationship".
        assert "coverage gap" in coverage["coverage_notice"]
        assert "complete" not in coverage["coverage_notice"].lower()

    def test_threshold_is_exposed(self, client: TestClient, api_prefix: str) -> None:
        body = client.get(f"{api_prefix}/meta/chains").json()
        assert body["stale_label_days_threshold"] == 30


class TestAddressLookup:
    def test_a_checksummed_query_finds_the_canonical_row(
        self, seeded_client: TestClient, api_prefix: str
    ) -> None:
        """The DPRD sec.17 format-mismatch guard, end to end."""
        response = seeded_client.get(
            f"{api_prefix}/vasps/addresses",
            params={"chain": "ethereum", "address": ETH_CHECKSUMMED},
        )
        assert response.status_code == 200

        body = response.json()
        assert body["is_labelled"] is True
        assert body["canonical_address"] == ETH_CANONICAL
        assert len(body["vasp_claims"]) == 1
        assert body["vasp_claims"][0]["vasp_name"] == "Acme Exchange"

    def test_an_unlabelled_address_is_reported_as_such(
        self, seeded_client: TestClient, api_prefix: str
    ) -> None:
        response = seeded_client.get(
            f"{api_prefix}/vasps/addresses",
            params={"chain": "ethereum", "address": derive_address("ethereum", "unknown")},
        )
        body = response.json()

        assert body["is_labelled"] is False
        assert body["vasp_claims"] == []
        assert body["has_conflicting_labels"] is False

    def test_every_claim_carries_its_provenance(
        self, seeded_client: TestClient, api_prefix: str
    ) -> None:
        body = seeded_client.get(
            f"{api_prefix}/vasps/addresses",
            params={"chain": "ethereum", "address": ETH_CANONICAL},
        ).json()
        entry = body["vasp_claims"][0]["entry"]

        for field in ("source", "source_url", "source_tier", "verification_status", "reliability"):
            assert entry[field] not in (None, "")
        assert entry["is_stale"] is False

    def test_an_invalid_address_returns_the_error_envelope(
        self, client: TestClient, api_prefix: str
    ) -> None:
        response = client.get(
            f"{api_prefix}/vasps/addresses",
            params={"chain": "ethereum", "address": "0xnothex"},
        )
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "INVALID_ADDRESS"

    def test_a_wrong_chain_address_suggests_the_right_chain(
        self, client: TestClient, api_prefix: str
    ) -> None:
        response = client.get(
            f"{api_prefix}/vasps/addresses",
            params={"chain": "ethereum", "address": derive_address("tron", "x")},
        )
        assert response.status_code == 422
        assert response.json()["error"]["details"]["suggested_chain"] == "tron"


class TestVaspDirectory:
    def test_list_reports_address_counts_and_chains(
        self, seeded_client: TestClient, api_prefix: str
    ) -> None:
        body = seeded_client.get(f"{api_prefix}/vasps").json()

        assert body["total"] == 1
        entry = body["vasps"][0]
        assert entry["slug"] == "acme-exchange"
        assert entry["address_count"] == 1
        assert entry["chains"] == ["ethereum"]
        # Unknown FIU-IND registration stays null rather than defaulting to false.
        assert entry["is_fiu_ind_registered"] is None

    def test_detail_includes_labelled_addresses(
        self, seeded_client: TestClient, api_prefix: str
    ) -> None:
        body = seeded_client.get(f"{api_prefix}/vasps/acme-exchange").json()

        assert body["name"] == "Acme Exchange"
        assert len(body["addresses"]) == 1
        assert body["addresses"][0]["address"] == ETH_CANONICAL

    def test_an_unknown_slug_is_a_clean_404(self, client: TestClient, api_prefix: str) -> None:
        response = client.get(f"{api_prefix}/vasps/does-not-exist")
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "NOT_FOUND"


class TestDatasetVersions:
    def test_versions_expose_sources_and_integrity(
        self, seeded_client: TestClient, api_prefix: str
    ) -> None:
        body = seeded_client.get(f"{api_prefix}/labels/versions").json()

        assert body["current_version"] == "api-test-1"
        version = body["versions"][0]
        assert version["integrity_is_clean"] is True
        assert version["is_stale"] is False

        source = version["sources"][0]
        assert source["url"] == "https://example.org/labels"
        assert source["licence"] == "test"
        assert len(source["sha256"]) == 64

    def test_an_empty_database_returns_no_versions(
        self, client: TestClient, api_prefix: str
    ) -> None:
        body = client.get(f"{api_prefix}/labels/versions").json()
        assert body["versions"] == []
        assert body["current_version"] is None


class TestHealthWithDatabase:
    def test_health_probes_the_database_for_real(self, client: TestClient, api_prefix: str) -> None:
        body = client.get(f"{api_prefix}/health").json()
        database = next(dep for dep in body["dependencies"] if dep["name"] == "database")

        # The SQLite fallback answers, so this reports ok — and says it is a fallback.
        assert database["status"] == "ok"
        assert "fallback" in (database["detail"] or "")


class TestConflictingLabels:
    def test_two_sources_disagreeing_are_both_returned(
        self, client: TestClient, api_prefix: str
    ) -> None:
        """DPRD sec.21: flag for manual review; do not silently pick one."""

        async def _seed(session: AsyncSession) -> None:
            await seed_label(session, slug="acme-exchange", name="Acme Exchange")
            await seed_label(
                session,
                slug="globex-exchange",
                name="Globex Exchange",
                source="Second source",
            )

        run_seed(client, _seed)

        body = client.get(
            f"{api_prefix}/vasps/addresses",
            params={"chain": "ethereum", "address": ETH_CANONICAL},
        ).json()

        assert body["has_conflicting_labels"] is True
        assert len(body["vasp_claims"]) == 2
        assert {claim["vasp_name"] for claim in body["vasp_claims"]} == {
            "Acme Exchange",
            "Globex Exchange",
        }
        assert "does not choose between them" in body["conflict_notice"]
