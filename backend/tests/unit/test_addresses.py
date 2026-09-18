"""Address validation and canonicalisation.

These tests guard the DPRD sec.17 failure mode "missed matches due to case-sensitivity /
format mismatches": if canonicalisation is wrong, every downstream match silently fails and
the system reports "no attribution found" for a wallet it should have matched.
"""

from __future__ import annotations

import pytest

from app.blockchain.addresses import (
    AddressErrorCode,
    b58check_decode,
    b58check_encode,
    canonicalize,
    is_eip55_checksum_valid,
    to_eip55,
    tron_base58_to_hex,
    tron_hex_to_base58,
    validate_address,
)
from app.schemas.common import Chain

# Well-known EIP-55 vectors from the specification itself.
EIP55_VECTORS = [
    "0x5aAeb6053F3E94C9b9A09f33669435E7Ef1BeAed",
    "0xfB6916095ca1df60bB79Ce92cE3Ea74c37c5d359",
    "0xdbF03B407c01E7cD3CBea99509d93f8DDDC8C6FB",
    "0xD1220A0cf47c7B9Be7A2E6BA89F429762e7b9aDb",
]


class TestEthereum:
    @pytest.mark.parametrize("address", EIP55_VECTORS)
    def test_official_eip55_vectors_round_trip(self, address: str) -> None:
        assert to_eip55(address.lower()) == address
        assert is_eip55_checksum_valid(address)

    @pytest.mark.parametrize("address", EIP55_VECTORS)
    def test_canonical_form_is_lowercase(self, address: str) -> None:
        result = validate_address(address, Chain.ETHEREUM)
        assert result.valid
        assert result.canonical_address == address.lower()
        # The display form keeps the checksum so an investigator can verify it by eye.
        assert result.display_address == address

    def test_all_lowercase_is_accepted_without_a_checksum_claim(self) -> None:
        result = validate_address(EIP55_VECTORS[0].lower(), Chain.ETHEREUM)
        assert result.valid
        # No mixed case means no checksum information; we must not claim it was verified.
        assert result.checksum_valid is None
        assert result.normalization_note is not None

    def test_mixed_case_with_a_bad_checksum_is_rejected(self) -> None:
        # Flip one character's case in a valid checksummed address.
        tampered = "0x5aAeb6053F3E94C9b9A09f33669435E7Ef1Beaed"
        result = validate_address(tampered, Chain.ETHEREUM)
        assert not result.valid
        assert result.error_code is AddressErrorCode.CHECKSUM_MISMATCH

    @pytest.mark.parametrize(
        ("address", "expected"),
        [
            ("", AddressErrorCode.EMPTY),
            ("5aAeb6053F3E94C9b9A09f33669435E7Ef1BeAed", AddressErrorCode.INVALID_CHARSET),
            ("0x5aAeb6053F3E94C9b9A09f33669435E7Ef1BeAe", AddressErrorCode.INVALID_LENGTH),
            ("0x5aAeb6053F3E94C9b9A09f33669435E7Ef1BeAeZ", AddressErrorCode.INVALID_CHARSET),
        ],
    )
    def test_malformed_inputs(self, address: str, expected: AddressErrorCode) -> None:
        result = validate_address(address, Chain.ETHEREUM)
        assert not result.valid
        assert result.error_code is expected

    def test_a_tron_address_suggests_the_right_chain(self) -> None:
        tron = tron_hex_to_base58("41" + "ab" * 20)
        result = validate_address(tron, Chain.ETHEREUM)
        assert not result.valid
        assert result.error_code is AddressErrorCode.WRONG_CHAIN_FORMAT
        assert result.suggested_chain is Chain.TRON


class TestTron:
    def test_base58check_round_trip(self) -> None:
        payload = bytes([0x41]) + bytes(range(20))
        encoded = b58check_encode(payload)
        assert encoded.startswith("T")
        assert len(encoded) == 34
        assert b58check_decode(encoded) == payload

    def test_hex_form_is_converted_to_canonical_base58(self) -> None:
        hex_form = "41" + "cd" * 20
        expected = tron_hex_to_base58(hex_form)

        result = validate_address(hex_form, Chain.TRON)
        assert result.valid
        assert result.canonical_address == expected
        assert result.normalization_note is not None
        assert tron_base58_to_hex(expected) == hex_form

    def test_a_corrupted_checksum_is_rejected(self) -> None:
        valid = tron_hex_to_base58("41" + "ef" * 20)
        # Change a character in the checksum region without changing the length.
        tampered = valid[:-1] + ("A" if valid[-1] != "A" else "B")

        result = validate_address(tampered, Chain.TRON)
        assert not result.valid
        assert result.error_code is AddressErrorCode.INVALID_BASE58_CHECKSUM

    def test_wrong_prefix_byte_is_rejected(self) -> None:
        # Structurally valid base58check, but not a Tron mainnet address (prefix 0x00).
        not_tron = b58check_encode(bytes([0x00]) + bytes(range(20)))
        result = validate_address(not_tron, Chain.TRON)
        assert not result.valid

    def test_an_ethereum_address_suggests_the_right_chain(self) -> None:
        result = validate_address(EIP55_VECTORS[0], Chain.TRON)
        assert not result.valid
        assert result.error_code is AddressErrorCode.WRONG_CHAIN_FORMAT
        assert result.suggested_chain is Chain.ETHEREUM


class TestUnsupportedChains:
    @pytest.mark.parametrize("chain", [Chain.BITCOIN, Chain.SOLANA, Chain.POLYGON])
    def test_roadmap_chains_report_clearly(self, chain: Chain) -> None:
        result = validate_address("anything", chain)
        assert not result.valid
        assert result.error_code is AddressErrorCode.CHAIN_NOT_SUPPORTED
        assert "not supported yet" in (result.error_message or "")


class TestCanonicalize:
    def test_canonicalize_is_idempotent(self) -> None:
        once = canonicalize(EIP55_VECTORS[0], Chain.ETHEREUM)
        assert canonicalize(once, Chain.ETHEREUM) == once

    def test_canonicalize_raises_on_invalid_input(self) -> None:
        with pytest.raises(ValueError, match="42 characters"):
            canonicalize("0xdeadbeef", Chain.ETHEREUM)

    def test_differently_cased_inputs_collapse_to_one_key(self) -> None:
        """The property that makes label matching work at all."""
        forms = [
            EIP55_VECTORS[1],
            EIP55_VECTORS[1].lower(),
            "0X" + EIP55_VECTORS[1][2:].upper(),
        ]
        assert len({canonicalize(form, Chain.ETHEREUM) for form in forms}) == 1
