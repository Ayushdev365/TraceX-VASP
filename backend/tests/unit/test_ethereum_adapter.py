"""Ethereum adapter: normalization, paging, direction, and failure handling.

All provider traffic is mocked with respx, so the suite is offline and deterministic — no
API key, no quota, no flakiness from a third party (DPRD sec.35: adapter regression tests on
every code change).
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import httpx
import pytest
import respx

from app.blockchain.ethereum import PROVIDER_RECORD_CAP, EthereumAdapter
from app.blockchain.registry import ProviderNotConfigured, get_adapter, is_chain_ready
from app.core.errors import (
    ChainNotSupported,
    InvalidAddress,
    UpstreamProviderError,
    UpstreamRateLimited,
)
from app.schemas.common import Chain, DataProvenance, Direction, TxKind, TxStatus

BASE_URL = "https://api.etherscan.io/v2/api"

SUBJECT = "0x742d35cc6634c0532925a3b844bc454e4438f44e"
COUNTERPARTY = "0x9ab1f4c5e0d2b3a6c7d8e9f0a1b2c3d4e5f60718"

NATIVE_TX = {
    "blockNumber": "18500000",
    "timeStamp": "1730000000",
    "hash": "0xAAA1",
    "from": SUBJECT,
    "to": COUNTERPARTY,
    "value": "9500000000000000000",  # 9.5 ETH
    "gas": "21000",
    "gasPrice": "20000000000",
    "gasUsed": "21000",
    "isError": "0",
    "txreceipt_status": "1",
}
TOKEN_TX = {
    "blockNumber": "18500100",
    "timeStamp": "1730001000",
    "hash": "0xBBB2",
    "from": SUBJECT,
    "to": COUNTERPARTY,
    "value": "1250435000",  # 1250.435 USDT
    "tokenSymbol": "USDT",
    "tokenDecimal": "6",
    "contractAddress": "0xDAC17F958D2EE523A2206206994597C13D831EC7",
    "logIndex": "42",
}
INTERNAL_TX = {
    "blockNumber": "18500200",
    "timeStamp": "1730002000",
    "hash": "0xCCC3",
    "from": SUBJECT,
    "to": COUNTERPARTY,
    "value": "1000000000000000000",
    "isError": "0",
    "type": "call",
}


def ok(records: list[dict[str, Any]]) -> httpx.Response:
    return httpx.Response(200, json={"status": "1", "message": "OK", "result": records})


def empty() -> httpx.Response:
    return httpx.Response(
        200, json={"status": "0", "message": "No transactions found", "result": []}
    )


@pytest.fixture
def adapter() -> EthereumAdapter:
    # No session: caching is exercised separately; here we want every call to hit the mock.
    return EthereumAdapter(session=None, api_key="test-key")


class TestNormalization:
    def test_native_transfer(self, adapter: EthereumAdapter) -> None:
        tx = adapter.normalize_transaction(NATIVE_TX)
        assert tx is not None
        assert tx.chain is Chain.ETHEREUM
        assert tx.kind is TxKind.NATIVE
        assert tx.status is TxStatus.SUCCESS
        assert tx.asset_symbol == "ETH"
        assert tx.amount == Decimal("9.5")
        assert tx.amount_raw == "9500000000000000000"
        assert tx.decimals == 18
        assert tx.block_timestamp == datetime(2024, 10, 27, 3, 33, 20, tzinfo=UTC)
        # 21000 * 20 gwei
        assert tx.fee == Decimal("0.00042")

    def test_hashes_and_addresses_are_canonicalised(self, adapter: EthereumAdapter) -> None:
        """Mixed-case provider output must not defeat matching (DPRD sec.17)."""
        tx = adapter.normalize_transaction(TOKEN_TX)
        assert tx is not None
        assert tx.tx_hash == "0xbbb2"
        assert tx.asset_contract == "0xdac17f958d2ee523a2206206994597c13d831ec7"

    def test_token_decimals_are_respected(self, adapter: EthereumAdapter) -> None:
        tx = adapter.normalize_transaction(TOKEN_TX)
        assert tx is not None
        assert tx.kind is TxKind.TOKEN
        assert tx.asset_symbol == "USDT"
        assert tx.decimals == 6
        # 6-decimal token: reading this as 18 decimals would understate it a trillion-fold.
        assert tx.amount == Decimal("1250.435")

    def test_internal_transfers_are_marked_as_such(self, adapter: EthereumAdapter) -> None:
        tx = adapter.normalize_transaction(INTERNAL_TX)
        assert tx is not None
        assert tx.kind is TxKind.INTERNAL

    def test_failed_transactions_are_flagged(self, adapter: EthereumAdapter) -> None:
        tx = adapter.normalize_transaction({**NATIVE_TX, "isError": "1"})
        assert tx is not None and tx.status is TxStatus.FAILED

        receipt_failed = adapter.normalize_transaction({**NATIVE_TX, "txreceipt_status": "0"})
        assert receipt_failed is not None and receipt_failed.status is TxStatus.FAILED

    @pytest.mark.parametrize(
        "record",
        [
            {**NATIVE_TX, "value": "0"},  # moves nothing
            {**NATIVE_TX, "to": ""},  # contract creation, no recipient
            {**NATIVE_TX, "hash": ""},
        ],
    )
    def test_records_with_no_traceable_movement_are_dropped(
        self, adapter: EthereumAdapter, record: dict[str, Any]
    ) -> None:
        assert adapter.normalize_transaction(record) is None

    def test_malformed_numbers_do_not_raise(self, adapter: EthereumAdapter) -> None:
        """A provider schema change must not crash a trace mid-run."""
        assert adapter.normalize_transaction({**NATIVE_TX, "value": "not-a-number"}) is None

        odd = adapter.normalize_transaction({**TOKEN_TX, "tokenDecimal": "??"})
        assert odd is not None and odd.decimals == 18

    def test_dedup_key_distinguishes_assets_in_one_hash(self, adapter: EthereumAdapter) -> None:
        native = adapter.normalize_transaction(NATIVE_TX)
        token = adapter.normalize_transaction({**TOKEN_TX, "hash": "0xAAA1"})
        assert native is not None and token is not None
        assert native.dedup_key != token.dedup_key


class TestFetching:
    @respx.mock
    async def test_outbound_transactions_are_returned(self, adapter: EthereumAdapter) -> None:
        respx.get(BASE_URL).mock(side_effect=[ok([NATIVE_TX]), ok([INTERNAL_TX])])

        page = await adapter.get_wallet_transactions(SUBJECT, limit=10)

        assert len(page.transactions) == 2
        assert page.complete is True
        assert page.provenance is DataProvenance.LIVE_API
        # Newest first, so a trimmed trace keeps the most recent flow.
        assert page.transactions[0].tx_hash == "0xccc3"

    @respx.mock
    async def test_direction_filters_the_result(self, adapter: EthereumAdapter) -> None:
        inbound = {**NATIVE_TX, "from": COUNTERPARTY, "to": SUBJECT, "hash": "0xDDD4"}
        respx.get(BASE_URL).mock(
            side_effect=[ok([NATIVE_TX, inbound]), empty(), ok([NATIVE_TX, inbound]), empty()]
        )

        out = await adapter.get_wallet_transactions(SUBJECT, direction=Direction.OUT)
        assert {tx.tx_hash for tx in out.transactions} == {"0xaaa1"}

        into = await adapter.get_wallet_transactions(SUBJECT, direction=Direction.IN)
        assert {tx.tx_hash for tx in into.transactions} == {"0xddd4"}

    @respx.mock
    async def test_token_transfers_are_fetched_separately(self, adapter: EthereumAdapter) -> None:
        respx.get(BASE_URL).mock(return_value=ok([TOKEN_TX]))

        page = await adapter.get_token_transfers(SUBJECT)
        assert len(page.transactions) == 1
        assert page.transactions[0].asset_symbol == "USDT"

    @respx.mock
    async def test_no_transactions_found_is_an_empty_result_not_an_error(
        self, adapter: EthereumAdapter
    ) -> None:
        """Etherscan reports 'none found' as status 0; treating it as a failure would turn a
        quiet wallet into a broken trace."""
        respx.get(BASE_URL).mock(return_value=empty())

        page = await adapter.get_wallet_transactions(SUBJECT)
        assert page.transactions == ()
        assert page.complete is True

    @respx.mock
    async def test_a_full_page_offers_a_cursor(self, adapter: EthereumAdapter) -> None:
        records = [{**NATIVE_TX, "hash": f"0x{i:04x}"} for i in range(5)]
        respx.get(BASE_URL).mock(side_effect=[ok(records), empty()])

        page = await adapter.get_wallet_transactions(SUBJECT, limit=5)
        assert page.next_cursor == "2"
        assert page.has_more is True

    @respx.mock
    async def test_a_partial_page_ends_pagination(self, adapter: EthereumAdapter) -> None:
        respx.get(BASE_URL).mock(side_effect=[ok([NATIVE_TX]), empty()])

        page = await adapter.get_wallet_transactions(SUBJECT, limit=100)
        assert page.next_cursor is None

    @respx.mock
    async def test_the_provider_record_cap_is_reported_as_incomplete(
        self, adapter: EthereumAdapter
    ) -> None:
        """Silently stopping short would look identical to 'no VASP exists' (DPRD sec.17)."""
        page_size = 100
        last_page = PROVIDER_RECORD_CAP // page_size
        records = [{**NATIVE_TX, "hash": f"0x{i:04x}"} for i in range(page_size)]
        respx.get(BASE_URL).mock(side_effect=[ok(records), empty()])

        page = await adapter.get_wallet_transactions(
            SUBJECT, limit=page_size, cursor=str(last_page)
        )

        assert page.complete is False
        assert page.next_cursor is None
        assert "caps a single query" in (page.truncation_reason or "")


class TestFailureHandling:
    @respx.mock
    async def test_rate_limit_in_a_200_body_is_surfaced_cleanly(
        self, adapter: EthereumAdapter
    ) -> None:
        respx.get(BASE_URL).mock(
            return_value=httpx.Response(
                200,
                json={"status": "0", "message": "NOTOK", "result": "Max rate limit reached"},
            )
        )
        with pytest.raises(UpstreamRateLimited):
            await adapter.get_wallet_transactions(SUBJECT)

    @respx.mock
    async def test_http_429_retries_then_surfaces(self, adapter: EthereumAdapter) -> None:
        route = respx.get(BASE_URL).mock(
            return_value=httpx.Response(429, headers={"Retry-After": "0"})
        )
        with pytest.raises(UpstreamRateLimited) as exc:
            await adapter.get_wallet_transactions(SUBJECT)

        assert route.call_count == 3  # MAX_ATTEMPTS
        assert exc.value.details["retry_after_s"] == 0

    @respx.mock
    async def test_a_server_error_retries_then_surfaces(self, adapter: EthereumAdapter) -> None:
        route = respx.get(BASE_URL).mock(return_value=httpx.Response(503))
        with pytest.raises(UpstreamProviderError):
            await adapter.get_wallet_transactions(SUBJECT)
        assert route.call_count == 3

    @respx.mock
    async def test_a_transient_error_then_success_recovers(self, adapter: EthereumAdapter) -> None:
        respx.get(BASE_URL).mock(side_effect=[httpx.Response(503), ok([NATIVE_TX]), empty()])
        page = await adapter.get_wallet_transactions(SUBJECT)
        assert len(page.transactions) == 1

    @respx.mock
    async def test_a_timeout_surfaces_as_a_provider_error(self, adapter: EthereumAdapter) -> None:
        respx.get(BASE_URL).mock(side_effect=httpx.ConnectTimeout("timed out"))
        with pytest.raises(UpstreamProviderError) as exc:
            await adapter.get_wallet_transactions(SUBJECT)
        assert exc.value.details["attempts"] == 3

    @respx.mock
    async def test_error_details_never_carry_the_api_key(self, adapter: EthereumAdapter) -> None:
        respx.get(BASE_URL).mock(return_value=httpx.Response(400, text="apikey=test-key bad"))
        with pytest.raises(UpstreamProviderError) as exc:
            await adapter.get_wallet_transactions(SUBJECT)

        rendered = f"{exc.value.message} {exc.value.details}"
        assert "test-key" not in rendered

    async def test_an_invalid_address_is_rejected_before_any_request(
        self, adapter: EthereumAdapter
    ) -> None:
        """No provider quota is spent on an address that cannot be right."""
        with respx.mock:
            route = respx.get(BASE_URL).mock(return_value=ok([]))
            with pytest.raises(InvalidAddress):
                await adapter.get_wallet_transactions("0xnothex")
            assert route.call_count == 0


class TestRegistry:
    def test_ethereum_resolves_when_a_key_is_configured(self) -> None:
        adapter = EthereumAdapter(api_key="k")
        assert adapter.chain is Chain.ETHEREUM

    def test_a_missing_key_is_its_own_condition(self) -> None:
        """'No key' and 'provider down' need different fixes, so they are different errors."""
        with pytest.raises(ProviderNotConfigured) as exc:
            get_adapter(Chain.ETHEREUM)
        assert exc.value.details["required_setting"] == "ETHERSCAN_API_KEY"

    @pytest.mark.parametrize(
        "chain", [Chain.TRON, Chain.BITCOIN, Chain.BNB, Chain.SOLANA, Chain.POLYGON]
    )
    def test_unimplemented_chains_fail_clearly(self, chain: Chain) -> None:
        with pytest.raises(ChainNotSupported) as exc:
            get_adapter(chain)
        assert "not supported yet" in exc.value.message
        assert exc.value.details["requested_chain"] == chain.value

    def test_readiness_reflects_configuration(self) -> None:
        # No key in the test environment, so nothing is ready — reported honestly.
        assert is_chain_ready(Chain.ETHEREUM) is False
        assert is_chain_ready(Chain.BITCOIN) is False
