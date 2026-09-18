"""Address validation endpoint, and provider-response caching."""

from __future__ import annotations

import httpx
import pytest
import respx
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.blockchain.ethereum import EthereumAdapter
from app.blockchain.http import SECRET_PARAMS, sanitize_params
from app.database.models import ApiResponseCache
from app.schemas.common import DataProvenance

BASE_URL = "https://api.etherscan.io/v2/api"
SUBJECT = "0x742d35cc6634c0532925a3b844bc454e4438f44e"
CHECKSUMMED = "0x5aAeb6053F3E94C9b9A09f33669435E7Ef1BeAed"


class TestValidateEndpoint:
    def test_a_valid_address_returns_both_forms(self, client: TestClient, api_prefix: str) -> None:
        body = client.post(
            f"{api_prefix}/addresses/validate",
            json={"address": CHECKSUMMED, "chain": "ethereum"},
        ).json()

        assert body["valid"] is True
        assert body["canonical_address"] == CHECKSUMMED.lower()
        assert body["display_address"] == CHECKSUMMED
        assert body["checksum_valid"] is True

    def test_an_invalid_address_is_a_200_with_valid_false(
        self, client: TestClient, api_prefix: str
    ) -> None:
        """This is a form-field check, so a rejection is a normal outcome, not an error."""
        response = client.post(
            f"{api_prefix}/addresses/validate",
            json={"address": "0xnothex", "chain": "ethereum"},
        )
        assert response.status_code == 200

        body = response.json()
        assert body["valid"] is False
        assert body["error_code"] == "INVALID_LENGTH"
        assert body["error_message"]

    def test_a_wrong_chain_address_suggests_the_right_one(
        self, client: TestClient, api_prefix: str
    ) -> None:
        body = client.post(
            f"{api_prefix}/addresses/validate",
            json={"address": "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t", "chain": "ethereum"},
        ).json()

        assert body["valid"] is False
        assert body["error_code"] == "WRONG_CHAIN_FORMAT"
        assert body["suggested_chain"] == "tron"

    def test_an_all_lowercase_address_makes_no_checksum_claim(
        self, client: TestClient, api_prefix: str
    ) -> None:
        body = client.post(
            f"{api_prefix}/addresses/validate",
            json={"address": CHECKSUMMED.lower(), "chain": "ethereum"},
        ).json()

        assert body["valid"] is True
        # No mixed case means no checksum information, so this stays null rather than true.
        assert body["checksum_valid"] is None
        assert body["normalization_note"]

    def test_a_roadmap_chain_is_reported_clearly(self, client: TestClient, api_prefix: str) -> None:
        body = client.post(
            f"{api_prefix}/addresses/validate",
            json={"address": "bc1qexample", "chain": "bitcoin"},
        ).json()

        assert body["valid"] is False
        assert body["error_code"] == "CHAIN_NOT_SUPPORTED"

    def test_an_unknown_chain_fails_validation(self, client: TestClient, api_prefix: str) -> None:
        response = client.post(
            f"{api_prefix}/addresses/validate",
            json={"address": SUBJECT, "chain": "dogecoin"},
        )
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "VALIDATION_ERROR"


class TestProviderCaching:
    @respx.mock
    async def test_a_second_identical_read_is_served_from_cache_and_labelled(
        self, db_session: AsyncSession
    ) -> None:
        """A warm-cache demo must never be reported as a fresh live pull."""
        route = respx.get(BASE_URL).mock(
            return_value=httpx.Response(200, json={"status": "1", "message": "OK", "result": []})
        )
        adapter = EthereumAdapter(session=db_session, api_key="test-key")

        first = await adapter.get_token_transfers(SUBJECT)
        assert first.provenance is DataProvenance.LIVE_API
        assert route.call_count == 1

        second = await adapter.get_token_transfers(SUBJECT)
        assert second.provenance is DataProvenance.CACHED
        assert second.api_calls == 0
        # No second provider call: the cache spared the quota.
        assert route.call_count == 1

    @respx.mock
    async def test_force_refresh_bypasses_the_cache(self, db_session: AsyncSession) -> None:
        route = respx.get(BASE_URL).mock(
            return_value=httpx.Response(200, json={"status": "1", "message": "OK", "result": []})
        )
        adapter = EthereumAdapter(session=db_session, api_key="test-key")

        await adapter.get_token_transfers(SUBJECT)
        await adapter.get_token_transfers(SUBJECT, force_refresh=True)
        assert route.call_count == 2

    @respx.mock
    async def test_the_cached_request_params_never_contain_the_key(
        self, db_session: AsyncSession
    ) -> None:
        respx.get(BASE_URL).mock(
            return_value=httpx.Response(200, json={"status": "1", "message": "OK", "result": []})
        )
        adapter = EthereumAdapter(session=db_session, api_key="super-secret-key")
        await adapter.get_token_transfers(SUBJECT)

        rows = (await db_session.execute(select(ApiResponseCache))).scalars().all()
        assert rows
        for row in rows:
            serialised = str(row.request_params)
            assert "super-secret-key" not in serialised
            assert not (set(row.request_params) & SECRET_PARAMS)

    @respx.mock
    async def test_each_distinct_query_gets_its_own_cache_row(
        self, db_session: AsyncSession
    ) -> None:
        respx.get(BASE_URL).mock(
            return_value=httpx.Response(200, json={"status": "1", "message": "OK", "result": []})
        )
        adapter = EthereumAdapter(session=db_session, api_key="test-key")

        await adapter.get_token_transfers(SUBJECT)
        await adapter.get_token_transfers(SUBJECT, cursor="2")

        count = await db_session.scalar(select(func.count()).select_from(ApiResponseCache))
        assert count == 2


@pytest.mark.parametrize("secret", sorted(SECRET_PARAMS))
def test_every_known_credential_param_is_stripped(secret: str) -> None:
    assert sanitize_params({secret: "value", "module": "account"}) == {"module": "account"}
