"""Tron adapter and MockAdapter.

The cross-chain schema-consistency test at the bottom is the DPRD sec.10 verification for
chain adapters: if Ethereum and Tron produce structurally different objects, every layer
above them has to know which chain it is looking at, and the adapter abstraction has failed.
"""

from __future__ import annotations

from dataclasses import fields
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import httpx
import pytest
import respx

from app.blockchain.addresses import canonicalize, tron_hex_to_base58
from app.blockchain.base import NormalizedTx
from app.blockchain.ethereum import EthereumAdapter
from app.blockchain.mock import MockAdapter, demo_subjects, mock_subject
from app.blockchain.registry import ProviderNotConfigured, adapter_provenance, get_adapter
from app.blockchain.tron import TronAdapter
from app.core.errors import ChainNotSupported, InvalidAddress, UpstreamProviderError
from app.schemas.common import Chain, DataProvenance, Direction, TxKind, TxStatus

BASE = "https://api.trongrid.io"

SUBJECT_HEX = "41" + "a1" * 20
SUBJECT = tron_hex_to_base58(SUBJECT_HEX)
PEER_HEX = "41" + "b2" * 20
PEER = tron_hex_to_base58(PEER_HEX)

# TronGrid returns hex addresses here, nested two levels deep.
NATIVE_TX: dict[str, Any] = {
    "txID": "ABC123DEF",
    "block_timestamp": 1_754_042_400_000,  # milliseconds
    "blockNumber": 65_000_000,
    "ret": [{"contractRet": "SUCCESS"}],
    "raw_data": {
        "contract": [
            {
                "type": "TransferContract",
                "parameter": {
                    "value": {
                        "owner_address": SUBJECT_HEX,
                        "to_address": PEER_HEX,
                        "amount": 125_500_000,  # 125.5 TRX in sun
                    }
                },
            }
        ]
    },
}

# The TRC-20 endpoint returns base58, pre-flattened.
TRC20_TX: dict[str, Any] = {
    "transaction_id": "DEAD99BEEF",
    "block_timestamp": 1_754_046_000_000,
    "from": SUBJECT,
    "to": PEER,
    "value": "48250000000",  # 48 250 USDT at 6 decimals
    "token_info": {
        "symbol": "USDT",
        "decimals": 6,
        "address": "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t",
    },
}


def canonical_demo_address(chain: Chain, seed: str) -> str:
    """A demo-fixture address in the canonical form the adapters emit."""
    from app.database.seeds.demo_fixtures import derive_address

    return canonicalize(derive_address(chain.value, seed), chain)


def body(records: list[dict[str, Any]], *, fingerprint: str | None = None) -> httpx.Response:
    meta: dict[str, Any] = {}
    if fingerprint:
        meta = {"fingerprint": fingerprint, "links": {"next": f"{BASE}/next"}}
    return httpx.Response(200, json={"success": True, "data": records, "meta": meta})


@pytest.fixture
def adapter() -> TronAdapter:
    return TronAdapter(session=None, api_key="test-key")


class TestTronNormalization:
    def test_native_transfer_from_the_nested_shape(self, adapter: TronAdapter) -> None:
        tx = adapter.normalize_transaction(NATIVE_TX)
        assert tx is not None
        assert tx.chain is Chain.TRON
        assert tx.kind is TxKind.NATIVE
        assert tx.asset_symbol == "TRX"
        assert tx.amount == Decimal("125.5")
        assert tx.amount_raw == "125500000"
        assert tx.decimals == 6
        assert tx.status is TxStatus.SUCCESS

    def test_hex_addresses_are_canonicalised_to_base58(self, adapter: TronAdapter) -> None:
        """Providers mix the two forms; a stored hex address would never match a label."""
        tx = adapter.normalize_transaction(NATIVE_TX)
        assert tx is not None
        assert tx.from_address == SUBJECT
        assert tx.to_address == PEER
        assert tx.from_address.startswith("T")

    def test_timestamps_are_milliseconds(self, adapter: TronAdapter) -> None:
        """Reading these as seconds would place every transaction in 1970."""
        tx = adapter.normalize_transaction(NATIVE_TX)
        assert tx is not None
        assert tx.block_timestamp == datetime(2025, 8, 1, 10, 0, tzinfo=UTC)
        assert tx.block_timestamp.year == 2025

    def test_non_transfer_contracts_are_skipped(self, adapter: TronAdapter) -> None:
        for contract_type in (
            "VoteWitnessContract",
            "TriggerSmartContract",
            "FreezeBalanceV2Contract",
        ):
            record = {
                **NATIVE_TX,
                "raw_data": {
                    "contract": [{**NATIVE_TX["raw_data"]["contract"][0], "type": contract_type}]
                },
            }
            assert adapter.normalize_transaction(record) is None

    def test_a_reverted_transaction_is_marked_failed(self, adapter: TronAdapter) -> None:
        tx = adapter.normalize_transaction({**NATIVE_TX, "ret": [{"contractRet": "REVERT"}]})
        assert tx is not None and tx.status is TxStatus.FAILED

    def test_missing_ret_is_treated_as_failed(self, adapter: TronAdapter) -> None:
        tx = adapter.normalize_transaction({**NATIVE_TX, "ret": []})
        assert tx is not None and tx.status is TxStatus.FAILED

    def test_trc20_transfer(self, adapter: TronAdapter) -> None:
        tx = adapter.normalize_transaction(TRC20_TX)
        assert tx is not None
        assert tx.kind is TxKind.TOKEN
        assert tx.asset_symbol == "USDT"
        assert tx.decimals == 6
        assert tx.amount == Decimal("48250")
        assert tx.asset_contract == "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t"

    def test_zero_value_and_malformed_records_are_dropped(self, adapter: TronAdapter) -> None:
        zero = {
            **NATIVE_TX,
            "raw_data": {
                "contract": [
                    {
                        "type": "TransferContract",
                        "parameter": {
                            "value": {
                                "owner_address": SUBJECT_HEX,
                                "to_address": PEER_HEX,
                                "amount": 0,
                            }
                        },
                    }
                ]
            },
        }
        assert adapter.normalize_transaction(zero) is None
        assert adapter.normalize_transaction({"txID": ""}) is None
        assert adapter.normalize_transaction({**NATIVE_TX, "raw_data": {}}) is None


class TestTronFetching:
    @respx.mock
    async def test_native_transfers_are_fetched(self, adapter: TronAdapter) -> None:
        respx.get(url__startswith=BASE).mock(return_value=body([NATIVE_TX]))

        page = await adapter.get_wallet_transactions(SUBJECT)
        assert len(page.transactions) == 1
        assert page.transactions[0].asset_symbol == "TRX"
        assert page.next_cursor is None

    @respx.mock
    async def test_token_transfers_are_fetched(self, adapter: TronAdapter) -> None:
        respx.get(url__startswith=BASE).mock(return_value=body([TRC20_TX]))

        page = await adapter.get_token_transfers(SUBJECT)
        assert len(page.transactions) == 1
        assert page.transactions[0].asset_symbol == "USDT"

    @respx.mock
    async def test_the_api_key_is_sent_as_a_header(self, adapter: TronAdapter) -> None:
        route = respx.get(url__startswith=BASE).mock(return_value=body([]))
        await adapter.get_token_transfers(SUBJECT)

        request = route.calls[0].request
        assert request.headers["TRON-PRO-API-KEY"] == "test-key"
        # And never in the URL, where it could be logged or cached.
        assert "test-key" not in str(request.url)

    @respx.mock
    async def test_a_fingerprint_becomes_a_cursor_only_with_a_next_link(
        self, adapter: TronAdapter
    ) -> None:
        """TronGrid returns a fingerprint on the last page too, which would loop forever."""
        respx.get(url__startswith=BASE).mock(return_value=body([TRC20_TX], fingerprint="fp1"))
        assert (await adapter.get_token_transfers(SUBJECT)).next_cursor == "fp1"

        respx.get(url__startswith=BASE).mock(
            return_value=httpx.Response(
                200, json={"success": True, "data": [TRC20_TX], "meta": {"fingerprint": "fp2"}}
            )
        )
        assert (await adapter.get_token_transfers(SUBJECT)).next_cursor is None

    @respx.mock
    async def test_direction_filters_the_result(self, adapter: TronAdapter) -> None:
        inbound = {**TRC20_TX, "from": PEER, "to": SUBJECT, "transaction_id": "IN1"}
        respx.get(url__startswith=BASE).mock(return_value=body([TRC20_TX, inbound]))

        out = await adapter.get_token_transfers(SUBJECT, direction=Direction.OUT)
        assert {tx.tx_hash for tx in out.transactions} == {"dead99beef"}

        into = await adapter.get_token_transfers(SUBJECT, direction=Direction.IN)
        assert {tx.tx_hash for tx in into.transactions} == {"in1"}

    @respx.mock
    async def test_an_unsuccessful_body_surfaces_cleanly(self, adapter: TronAdapter) -> None:
        respx.get(url__startswith=BASE).mock(
            return_value=httpx.Response(200, json={"success": False, "error": "bad request"})
        )
        with pytest.raises(UpstreamProviderError):
            await adapter.get_token_transfers(SUBJECT)

    @respx.mock
    async def test_an_unexpected_body_surfaces_cleanly(self, adapter: TronAdapter) -> None:
        respx.get(url__startswith=BASE).mock(
            return_value=httpx.Response(200, json={"success": True, "data": "not-a-list"})
        )
        with pytest.raises(UpstreamProviderError):
            await adapter.get_token_transfers(SUBJECT)

    async def test_an_ethereum_address_is_rejected_before_any_request(
        self, adapter: TronAdapter
    ) -> None:
        with respx.mock:
            route = respx.get(url__startswith=BASE).mock(return_value=body([]))
            with pytest.raises(InvalidAddress):
                await adapter.get_token_transfers("0x742d35cc6634c0532925a3b844bc454e4438f44e")
            assert route.call_count == 0


class TestMockAdapter:
    @pytest.mark.parametrize("chain", [Chain.ETHEREUM, Chain.TRON])
    async def test_everything_is_labelled_mock_demo(self, chain: Chain) -> None:
        """The property that stops synthetic data being mistaken for real blockchain data."""
        adapter = MockAdapter(chain)
        assert adapter.provenance is DataProvenance.MOCK_DEMO

        page = await adapter.get_wallet_transactions(mock_subject(chain, "clean"))
        assert page.provenance is DataProvenance.MOCK_DEMO
        assert page.transactions
        assert all(tx.provenance is DataProvenance.MOCK_DEMO for tx in page.transactions)

    @pytest.mark.parametrize("chain", [Chain.ETHEREUM, Chain.TRON])
    async def test_the_clean_scenario_reaches_a_demo_vasp_in_three_hops(self, chain: Chain) -> None:
        adapter = MockAdapter(chain)
        subject = mock_subject(chain, "clean")

        hop1 = await adapter.get_wallet_transactions(subject)
        first = max(hop1.transactions, key=lambda tx: tx.amount)
        hop2 = await adapter.get_wallet_transactions(first.to_address)
        hop3 = await adapter.get_wallet_transactions(hop2.transactions[0].to_address)

        expected = canonical_demo_address(
            chain,
            "meridian/eth/deposit/1" if chain is Chain.ETHEREUM else "meridian/trx/deposit/1",
        )
        assert expected in {tx.to_address for tx in hop3.transactions}

    @pytest.mark.parametrize("chain", [Chain.ETHEREUM, Chain.TRON])
    async def test_the_mixer_scenario_routes_through_a_demo_mixer(self, chain: Chain) -> None:
        adapter = MockAdapter(chain)
        page = await adapter.get_token_transfers(mock_subject(chain, "mixer"))

        mixer = canonical_demo_address(
            chain,
            "obscura/eth/router/1" if chain is Chain.ETHEREUM else "obscura/trx/router/1",
        )
        assert {tx.to_address for tx in page.transactions} == {mixer}

    async def test_results_are_deterministic_across_instances(self) -> None:
        """Repeatability protocol: the same trace must reproduce exactly (DPRD sec.48 task 31)."""
        subject = mock_subject(Chain.ETHEREUM, "clean")
        first = await MockAdapter(Chain.ETHEREUM).get_wallet_transactions(subject)
        second = await MockAdapter(Chain.ETHEREUM).get_wallet_transactions(subject)

        assert [tx.dedup_key for tx in first.transactions] == [
            tx.dedup_key for tx in second.transactions
        ]
        assert [tx.tx_hash for tx in first.transactions] == [
            tx.tx_hash for tx in second.transactions
        ]

    async def test_an_unknown_address_still_yields_a_graph(self) -> None:
        adapter = MockAdapter(Chain.ETHEREUM)
        page = await adapter.get_wallet_transactions("0x742d35cc6634c0532925a3b844bc454e4438f44e")
        assert len(page.transactions) == 2
        assert all(tx.amount > 0 for tx in page.transactions)

    async def test_inbound_direction_is_supported(self) -> None:
        adapter = MockAdapter(Chain.ETHEREUM)
        subject = mock_subject(Chain.ETHEREUM, "clean")
        outbound = await adapter.get_wallet_transactions(subject)

        inbound = await adapter.get_wallet_transactions(
            outbound.transactions[0].to_address, direction=Direction.IN
        )
        assert subject in {tx.from_address for tx in inbound.transactions}

    def test_demo_subjects_are_valid_and_distinct(self) -> None:
        for chain in (Chain.ETHEREUM, Chain.TRON):
            subjects = demo_subjects(chain)
            assert set(subjects) == {"clean", "mixer", "dead_end"}
            assert len(set(subjects.values())) == 3
            adapter = MockAdapter(chain)
            assert all(adapter.validate_address(a).valid for a in subjects.values())

    def test_an_unsupported_chain_has_no_mock_data(self) -> None:
        with pytest.raises(ValueError, match="no mock data"):
            MockAdapter(Chain.BITCOIN)


class TestRegistry:
    def test_both_mvp_chains_need_their_own_key(self) -> None:
        for chain, setting in (
            (Chain.ETHEREUM, "ETHERSCAN_API_KEY"),
            (Chain.TRON, "TRONGRID_API_KEY"),
        ):
            with pytest.raises(ProviderNotConfigured) as exc:
                get_adapter(chain)
            assert exc.value.details["required_setting"] == setting
            # The message points at the offline alternative rather than dead-ending.
            assert "USE_MOCK_CHAIN_DATA" in exc.value.message

    @pytest.mark.parametrize("chain", [Chain.BITCOIN, Chain.BNB, Chain.SOLANA, Chain.POLYGON])
    def test_roadmap_chains_fail_clearly(self, chain: Chain) -> None:
        with pytest.raises(ChainNotSupported) as exc:
            get_adapter(chain)
        assert sorted(exc.value.details["supported_chains"]) == ["ethereum", "tron"]

    def test_mock_mode_is_opt_in_and_never_a_fallback(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from app.config import get_settings

        # Without the flag, a missing key is an error — not a silent switch to mock data.
        assert adapter_provenance(Chain.TRON) is None

        settings = get_settings()
        monkeypatch.setattr(settings, "use_mock_chain_data", True)
        assert isinstance(get_adapter(Chain.TRON), MockAdapter)
        assert adapter_provenance(Chain.TRON) is DataProvenance.MOCK_DEMO
        # Still never invents support for a roadmap chain.
        with pytest.raises(ChainNotSupported):
            get_adapter(Chain.BITCOIN)


class TestCrossChainSchemaConsistency:
    """DPRD sec.10: adapters must produce structurally identical objects."""

    def test_every_adapter_returns_the_same_fields_and_types(self) -> None:
        eth = EthereumAdapter(api_key="k").normalize_transaction(
            {
                "hash": "0xa",
                "timeStamp": "1730000000",
                "from": "0x" + "a" * 40,
                "to": "0x" + "b" * 40,
                "value": "1000000000000000000",
            }
        )
        tron = TronAdapter(api_key="k").normalize_transaction(NATIVE_TX)
        assert eth is not None and tron is not None

        expected = {f.name for f in fields(NormalizedTx)}
        for tx in (eth, tron):
            assert {f.name for f in fields(tx)} == expected
            assert isinstance(tx.amount, Decimal)
            assert isinstance(tx.amount_raw, str)
            assert tx.block_timestamp.tzinfo is not None  # always UTC-aware
            assert isinstance(tx.chain, Chain)
            assert isinstance(tx.kind, TxKind)
            assert isinstance(tx.status, TxStatus)

    def test_amounts_survive_a_round_trip_exactly(self) -> None:
        """Float arithmetic would lose the low digits of an 18-decimal amount."""
        tron = TronAdapter(api_key="k").normalize_transaction(TRC20_TX)
        assert tron is not None
        assert str(int(tron.amount * (Decimal(10) ** tron.decimals))) == tron.amount_raw
