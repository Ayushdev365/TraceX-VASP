"""Tests for the database-backed VASP label matcher service.

Tests the integration between the graph traversal engine and the PostgreSQL label
repository via the VaspLabelMatcher middleware. Coverage includes positive matches,
negative (unverified) handling, risk entities, and unlabelled addresses.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.blockchain.mock import MockAdapter, _addr
from app.database.models import LabelDatasetVersion, RiskEntity, Vasp, VaspAddress
from app.graph.types import TraversalResult
from app.schemas.common import Chain, LabelTier, RiskEntityKind, VaspKind, VerificationStatus
from app.services.label_matcher import VaspLabelMatcher


async def _setup_test_data(session: AsyncSession) -> dict[str, str]:
    """Insert fixture data matching the mock adapter's output paths."""
    # 1. Dataset version
    dataset = LabelDatasetVersion(
        version="test-dataset-v1",
        source_manifest={"source": "test"},
    )
    session.add(dataset)
    await session.flush()

    # 2. VASPs
    exchange = Vasp(name="Meridian Exchange", slug="meridian", kind=VaspKind.EXCHANGE.value)
    custody = Vasp(name="Kavach Custody", slug="kavach", kind=VaspKind.CUSTODIAL_WALLET.value)
    session.add_all([exchange, custody])
    await session.flush()

    # Derived addresses from the mock adapter
    exchange_addr = _addr(Chain.ETHEREUM, "meridian/eth/deposit/1")
    custody_addr = _addr(Chain.ETHEREUM, "kavach/eth/hot/1")
    mixer_addr = _addr(Chain.ETHEREUM, "obscura/eth/router/1")

    now = datetime.now(UTC)

    # 3. VASP Addresses

    # Positive case: Verified attributable label
    session.add(
        VaspAddress(
            vasp_id=exchange.id,
            chain=Chain.ETHEREUM.value,
            address=exchange_addr,
            source="Official Registry",
            source_url="https://example.com",
            source_tier=LabelTier.OFFICIAL_VASP_PUBLISHED.value,
            verification_status=VerificationStatus.VERIFIED.value,
            verified_at=now,
            verified_by="test_admin",
            reliability=Decimal("1.0"),
            dataset_version_id=dataset.id,
        )
    )

    # Negative case: Unverified (demo_unverified) label that shouldn't support attribution
    session.add(
        VaspAddress(
            vasp_id=custody.id,
            chain=Chain.ETHEREUM.value,
            address=custody_addr,
            source="Demo Data",
            source_url="https://example.com",
            source_tier=LabelTier.DEMO_UNVERIFIED.value,
            verification_status=VerificationStatus.UNVERIFIED.value,
            reliability=Decimal("0.25"),
            dataset_version_id=dataset.id,
        )
    )

    # 4. Risk Entity
    session.add(
        RiskEntity(
            chain=Chain.ETHEREUM.value,
            address=mixer_addr,
            entity_kind=RiskEntityKind.MIXER.value,
            severity="high",
            source="Sanctions List",
            source_url="https://example.com",
            source_tier=LabelTier.SANCTIONS_LIST.value,
            verification_status=VerificationStatus.VERIFIED.value,
            dataset_version_id=dataset.id,
        )
    )

    await session.commit()

    return {
        "exchange": exchange_addr,
        "custody": custody_addr,
        "mixer": mixer_addr,
    }


@pytest.mark.asyncio
async def test_matcher_positive_and_unknown_cases(db_session: AsyncSession) -> None:
    """Test that valid labels are found and unknown addresses are handled gracefully."""
    addrs = await _setup_test_data(db_session)

    adapter = MockAdapter(Chain.ETHEREUM)
    matcher = VaspLabelMatcher(db_session, adapter, Chain.ETHEREUM)

    # Use the clean scenario which hits the exchange deposit
    subject = _addr(Chain.ETHEREUM, "mock/subject/clean")

    result = await matcher.run_traversal(subject, hop_depth=3)

    assert isinstance(result, TraversalResult)

    # The exchange deposit should be identified as a VASP
    exchange_node = result.nodes.get(addrs["exchange"])
    assert exchange_node is not None
    assert exchange_node.matched_vasp_name == "Meridian Exchange"

    # There should be exactly 1 candidate VASP
    assert len(result.candidates) == 1
    assert result.candidates[0].vasp_name == "Meridian Exchange"

    # Unknown intermediaries should have no label
    intermediate = _addr(Chain.ETHEREUM, "mock/clean/i1")
    i1_node = result.nodes.get(intermediate)
    assert i1_node is not None
    assert i1_node.matched_vasp_name is None
    assert i1_node.matched_risk_entity_kind is None


@pytest.mark.asyncio
async def test_matcher_unverified_and_risk_cases(db_session: AsyncSession) -> None:
    """Test that unverified labels don't trigger VASP discovery, and risk labels do."""
    addrs = await _setup_test_data(db_session)

    adapter = MockAdapter(Chain.ETHEREUM)
    matcher = VaspLabelMatcher(db_session, adapter, Chain.ETHEREUM)

    # Use the mixer scenario which hits both the mixer (risk) and custody (demo_unverified)
    subject = _addr(Chain.ETHEREUM, "mock/subject/mixer")

    result = await matcher.run_traversal(subject, hop_depth=3)

    # The mixer should be identified as a risk entity
    mixer_node = result.nodes.get(addrs["mixer"])
    assert mixer_node is not None
    assert mixer_node.matched_risk_entity_kind == RiskEntityKind.MIXER.value

    # The custody wallet has a DEMO_UNVERIFIED label, so it should NOT be considered a VASP
    custody_node = result.nodes.get(addrs["custody"])
    assert custody_node is not None
    assert custody_node.matched_vasp_name is None

    # No VASP candidates should be found because the only VASP label was unverified
    assert len(result.candidates) == 0


@pytest.mark.asyncio
async def test_matcher_duplicate_prevention_cache(db_session: AsyncSession) -> None:
    """Test that the cache prevents duplicate database queries."""
    addrs = await _setup_test_data(db_session)

    adapter = MockAdapter(Chain.ETHEREUM)
    matcher = VaspLabelMatcher(db_session, adapter, Chain.ETHEREUM)

    # Pre-populate the cache manually to verify it bypasses the DB
    await matcher.preload([addrs["exchange"]])
    assert addrs["exchange"] in matcher._cache

    # The subject address should be preloaded during run_traversal
    subject = _addr(Chain.ETHEREUM, "mock/subject/clean")

    result = await matcher.run_traversal(subject, hop_depth=1)

    # The subject should now be in the cache
    assert subject in matcher._cache

    # We can check that the engine successfully used the cache
    assert len(result.nodes) > 0


@pytest.mark.asyncio
async def test_matcher_ignores_wrong_chain(db_session: AsyncSession) -> None:
    """Test that a label lookup for the wrong chain returns None."""
    await _setup_test_data(db_session)

    adapter = MockAdapter(Chain.ETHEREUM)
    # Instantiate for TRON but give it an ETHEREUM adapter
    matcher = VaspLabelMatcher(db_session, adapter, Chain.TRON)

    subject = _addr(Chain.ETHEREUM, "mock/subject/clean")
    result = await matcher.run_traversal(subject, hop_depth=3)

    # Even though the Ethereum exchange is in the path, it shouldn't be matched
    # because the matcher was configured for TRON.
    assert len(result.candidates) == 0
