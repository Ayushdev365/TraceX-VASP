"""End-to-end trace investigation API tests."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, cast

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.blockchain.mock import _addr, mock_subject
from app.database.models import Base, LabelDatasetVersion, RiskEntity, Vasp, VaspAddress
from app.deps import get_session
from app.main import create_app
from app.schemas.common import Chain, LabelTier, RiskEntityKind, VaspKind, VerificationStatus
from app.services.trace_store import clear_trace_results


async def _create_schema(db_path: Path) -> None:
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}", poolclass=NullPool)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    await engine.dispose()


async def _seed_trace_labels(db_path: Path) -> None:
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}", poolclass=NullPool)
    maker = async_sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)
    async with maker() as session:
        dataset = LabelDatasetVersion(
            version="trace-api-test-labels",
            source_manifest={"source": "trace-api-test"},
        )
        session.add(dataset)
        await session.flush()

        exchange = Vasp(name="Meridian Exchange", slug="meridian", kind=VaspKind.EXCHANGE.value)
        custody = Vasp(name="Kavach Custody", slug="kavach", kind=VaspKind.CUSTODIAL_WALLET.value)
        session.add_all([exchange, custody])
        await session.flush()

        now = datetime.now(UTC)
        session.add(
            VaspAddress(
                vasp_id=exchange.id,
                chain=Chain.ETHEREUM.value,
                address=_addr(Chain.ETHEREUM, "meridian/eth/deposit/1"),
                source="Official Registry",
                source_url="https://example.com/meridian",
                source_tier=LabelTier.OFFICIAL_VASP_PUBLISHED.value,
                verification_status=VerificationStatus.VERIFIED.value,
                verified_at=now,
                verified_by="test_admin",
                reliability=Decimal("1.0"),
                dataset_version_id=dataset.id,
            )
        )
        session.add(
            VaspAddress(
                vasp_id=custody.id,
                chain=Chain.ETHEREUM.value,
                address=_addr(Chain.ETHEREUM, "kavach/eth/hot/1"),
                source="Demo Data",
                source_url="https://example.com/kavach",
                source_tier=LabelTier.DEMO_UNVERIFIED.value,
                verification_status=VerificationStatus.UNVERIFIED.value,
                reliability=Decimal("0.25"),
                dataset_version_id=dataset.id,
            )
        )
        session.add(
            RiskEntity(
                chain=Chain.ETHEREUM.value,
                address=_addr(Chain.ETHEREUM, "obscura/eth/router/1"),
                entity_kind=RiskEntityKind.MIXER.value,
                severity="high",
                source="Sanctions List",
                source_url="https://example.com/obscura",
                source_tier=LabelTier.SANCTIONS_LIST.value,
                verification_status=VerificationStatus.VERIFIED.value,
                dataset_version_id=dataset.id,
            )
        )
        await session.commit()
    await engine.dispose()


@pytest.fixture
def trace_client(tmp_path: Path) -> Iterator[TestClient]:
    clear_trace_results()
    db_path = tmp_path / "trace-api.db"
    asyncio.run(_create_schema(db_path))
    asyncio.run(_seed_trace_labels(db_path))

    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}", poolclass=NullPool)
    maker = async_sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)

    async def _override() -> AsyncIterator[AsyncSession]:
        async with maker() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    app = create_app()
    app.dependency_overrides[get_session] = _override
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.clear()
    asyncio.run(engine.dispose())
    clear_trace_results()


def _post_trace(
    trace_client: TestClient,
    api_prefix: str,
    *,
    scenario: str,
    hop_depth: int = 3,
) -> dict[str, Any]:
    response = trace_client.post(
        f"{api_prefix}/traces",
        json={
            "address": mock_subject(Chain.ETHEREUM, scenario),
            "chain": "ethereum",
            "hop_depth": hop_depth,
            "data_mode": "mock",
        },
    )
    assert response.status_code == 200, response.text
    return cast(dict[str, Any], response.json())


def test_successful_mock_investigation_returns_vasp_attribution(
    trace_client: TestClient,
    api_prefix: str,
) -> None:
    body = _post_trace(trace_client, api_prefix, scenario="clean")

    assert body["status"] == "completed"
    assert body["data_provenance"] == "mock_demo"
    assert body["primary_attribution"]["vasp_name"] == "Meridian Exchange"
    assert body["primary_attribution"]["score"] >= 35
    assert body["vasp_candidates"][0]["path"][0] == body["canonical_address"]
    assert body["risk_indicators"] == []
    assert str(body["provenance_note"]).startswith("Synthetic mock-chain data")


def test_get_trace_returns_stored_result(trace_client: TestClient, api_prefix: str) -> None:
    created = _post_trace(trace_client, api_prefix, scenario="clean")

    fetched = trace_client.get(f"{api_prefix}/traces/{created['trace_id']}")

    assert fetched.status_code == 200
    assert fetched.json() == created


def test_invalid_address_returns_error(trace_client: TestClient, api_prefix: str) -> None:
    response = trace_client.post(
        f"{api_prefix}/traces",
        json={
            "address": "0xnothex",
            "chain": "ethereum",
            "hop_depth": 3,
            "data_mode": "mock",
        },
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "INVALID_ADDRESS"


def test_auto_mode_without_provider_key_is_explicit_error(
    trace_client: TestClient,
    api_prefix: str,
) -> None:
    response = trace_client.post(
        f"{api_prefix}/traces",
        json={
            "address": mock_subject(Chain.ETHEREUM, "clean"),
            "chain": "ethereum",
            "hop_depth": 3,
        },
    )

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "PROVIDER_NOT_CONFIGURED"


def test_no_attribution_path_is_explicit(trace_client: TestClient, api_prefix: str) -> None:
    body = _post_trace(trace_client, api_prefix, scenario="dead_end")

    assert body["primary_attribution"] is None
    assert body["attributions"] == []
    assert body["no_attribution_reason"] == "no_attributable_vasp_reached"
    assert "no reliable VASP attribution" in body["evidence_summary"]


def test_risk_indicators_are_returned_without_vasp_attribution(
    trace_client: TestClient,
    api_prefix: str,
) -> None:
    body = _post_trace(trace_client, api_prefix, scenario="mixer")
    risk_indicators = cast(list[dict[str, Any]], body["risk_indicators"])
    kinds = {indicator["kind"] for indicator in risk_indicators}

    assert body["primary_attribution"] is None
    assert body["no_attribution_reason"] == "no_attributable_vasp_reached"
    assert "mixer_interaction" in kinds
    assert all("criminal" not in str(indicator["summary"]).lower() for indicator in risk_indicators)


def test_repeated_mock_requests_are_deterministic(
    trace_client: TestClient,
    api_prefix: str,
) -> None:
    first = _post_trace(trace_client, api_prefix, scenario="clean")
    second = _post_trace(trace_client, api_prefix, scenario="clean")

    assert second["trace_id"] == first["trace_id"]
    assert second["discovered_addresses"] == first["discovered_addresses"]
    assert second["edges"] == first["edges"]
    assert second["attributions"] == first["attributions"]


def test_unsupported_chain_returns_clear_error(trace_client: TestClient, api_prefix: str) -> None:
    response = trace_client.post(
        f"{api_prefix}/traces",
        json={
            "address": "bc1qexample",
            "chain": "bitcoin",
            "hop_depth": 3,
            "data_mode": "mock",
        },
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "CHAIN_NOT_SUPPORTED"


def test_demo_subjects_are_available(trace_client: TestClient, api_prefix: str) -> None:
    response = trace_client.get(f"{api_prefix}/traces/demo-subjects")

    assert response.status_code == 200
    body = response.json()
    assert body["subjects"]["ethereum"]["clean"] == mock_subject(Chain.ETHEREUM, "clean")
    assert body["subjects"]["ethereum"]["mixer"] == mock_subject(Chain.ETHEREUM, "mixer")


def test_json_report_is_rendered_from_stored_trace(
    trace_client: TestClient, api_prefix: str
) -> None:
    created = _post_trace(trace_client, api_prefix, scenario="clean")

    first = trace_client.get(f"{api_prefix}/traces/{created['trace_id']}/report.json")
    second = trace_client.get(f"{api_prefix}/traces/{created['trace_id']}/report.json")

    assert first.status_code == 200
    assert first.json()["trace_id"] == created["trace_id"]
    assert first.json()["payload"]["primary_attribution"]["vasp_name"] == "Meridian Exchange"
    assert first.json()["content_sha256"] == second.json()["content_sha256"]

    pdf = trace_client.get(f"{api_prefix}/traces/{created['trace_id']}/report.pdf")
    assert pdf.status_code == 200
    assert pdf.headers["content-type"] == "application/pdf"
    assert pdf.content.startswith(b"%PDF")


def test_disclosure_requires_accepted_review(trace_client: TestClient, api_prefix: str) -> None:
    created = _post_trace(trace_client, api_prefix, scenario="clean")

    blocked = trace_client.post(f"{api_prefix}/traces/{created['trace_id']}/disclosure")
    assert blocked.status_code == 409
    assert blocked.json()["error"]["code"] == "REVIEW_REQUIRED"

    review = trace_client.post(
        f"{api_prefix}/traces/{created['trace_id']}/review",
        json={"decision": "accepted", "note": "Reviewed for demo."},
    )
    assert review.status_code == 200

    disclosure = trace_client.post(f"{api_prefix}/traces/{created['trace_id']}/disclosure")
    body = disclosure.json()
    assert disclosure.status_code == 200
    assert body["mode"] == "mock_demo"
    assert body["payload"]["primary_vasp"]["vasp_name"] == "Meridian Exchange"
    assert "DEMO / MOCK SAHYOG REQUEST" in body["banner"]
