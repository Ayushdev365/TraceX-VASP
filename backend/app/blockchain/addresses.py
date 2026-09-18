"""Chain-specific address validation and canonicalisation.

This module is the single boundary at which an address becomes trustworthy. Everything
downstream — the label store, the traversal engine, the matcher — assumes it is working with
a *canonical* address, because a case-sensitivity or format mismatch is one of the DPRD's
named failure modes: "missed matches due to case-sensitivity/format mismatches" (DPRD sec.17).

Canonical forms:

* Ethereum — lowercase ``0x``-prefixed hex. Mixed-case input is checksum-verified per
  EIP-55 before being accepted; an all-lowercase or all-uppercase address carries no
  checksum information and is accepted without that check.
* Tron — base58check ``T…``. Hex ``41…`` form is accepted and converted, because block
  explorers and APIs disagree about which they return.

Pure functions only: no I/O, no settings, no database. That is what lets the importer
(Phase 2) and the adapters (Phase 3/4) share it without a dependency cycle.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from enum import StrEnum

from Crypto.Hash import keccak

from app.schemas.common import Chain

_ETH_RE = re.compile(r"^0x[0-9a-fA-F]{40}$")
_TRON_HEX_RE = re.compile(r"^(?:0x)?41[0-9a-fA-F]{40}$")
_B58_ALPHABET = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
_B58_INDEX = {char: index for index, char in enumerate(_B58_ALPHABET)}

TRON_ADDRESS_PREFIX = 0x41


class AddressErrorCode(StrEnum):
    """Machine codes surfaced by ``POST /addresses/validate`` (API contract sec.4)."""

    EMPTY = "EMPTY"
    INVALID_LENGTH = "INVALID_LENGTH"
    INVALID_CHARSET = "INVALID_CHARSET"
    CHECKSUM_MISMATCH = "CHECKSUM_MISMATCH"
    INVALID_BASE58_CHECKSUM = "INVALID_BASE58_CHECKSUM"
    WRONG_CHAIN_FORMAT = "WRONG_CHAIN_FORMAT"
    CHAIN_NOT_SUPPORTED = "CHAIN_NOT_SUPPORTED"


@dataclass(frozen=True, slots=True)
class AddressValidation:
    """Outcome of validating one address against one chain."""

    valid: bool
    chain: Chain
    canonical_address: str | None = None
    display_address: str | None = None
    checksum_valid: bool | None = None
    normalization_note: str | None = None
    error_code: AddressErrorCode | None = None
    error_message: str | None = None
    suggested_chain: Chain | None = None


# ─── base58check ────────────────────────────────────────────────────────────────


def b58_encode(payload: bytes) -> str:
    """Base58 encode, preserving leading-zero bytes as ``1`` characters."""
    value = int.from_bytes(payload, "big")
    encoded = ""
    while value:
        value, remainder = divmod(value, 58)
        encoded = _B58_ALPHABET[remainder] + encoded
    leading_zeros = len(payload) - len(payload.lstrip(b"\x00"))
    return "1" * leading_zeros + encoded


def b58_decode(encoded: str) -> bytes:
    """Base58 decode. Raises ``ValueError`` on any character outside the alphabet."""
    value = 0
    for char in encoded:
        try:
            value = value * 58 + _B58_INDEX[char]
        except KeyError as exc:
            raise ValueError(f"invalid base58 character {char!r}") from exc
    decoded = value.to_bytes((value.bit_length() + 7) // 8, "big")
    leading_ones = len(encoded) - len(encoded.lstrip("1"))
    return b"\x00" * leading_ones + decoded


def _b58check_checksum(payload: bytes) -> bytes:
    return hashlib.sha256(hashlib.sha256(payload).digest()).digest()[:4]


def b58check_encode(payload: bytes) -> str:
    return b58_encode(payload + _b58check_checksum(payload))


def b58check_decode(encoded: str) -> bytes:
    """Decode and verify the 4-byte trailing checksum. Raises ``ValueError`` if it fails."""
    raw = b58_decode(encoded)
    if len(raw) < 5:
        raise ValueError("base58check payload too short")
    payload, checksum = raw[:-4], raw[-4:]
    if _b58check_checksum(payload) != checksum:
        raise ValueError("base58check checksum mismatch")
    return payload


# ─── Ethereum ───────────────────────────────────────────────────────────────────


def keccak256(data: bytes) -> bytes:
    digest = keccak.new(digest_bits=256)
    digest.update(data)
    return digest.digest()


def to_eip55(address: str) -> str:
    """Return the EIP-55 mixed-case checksum form of a 0x-prefixed hex address."""
    body = address[2:].lower()
    digest = keccak256(body.encode("ascii")).hex()
    return "0x" + "".join(
        char.upper() if int(digest[index], 16) >= 8 else char for index, char in enumerate(body)
    )


def is_eip55_checksum_valid(address: str) -> bool:
    return to_eip55(address) == address


def _validate_ethereum(raw: str) -> AddressValidation:
    if _TRON_HEX_RE.match(raw) or (raw.startswith("T") and len(raw) == 34):
        return AddressValidation(
            valid=False,
            chain=Chain.ETHEREUM,
            error_code=AddressErrorCode.WRONG_CHAIN_FORMAT,
            error_message="This looks like a Tron address. Select Tron instead.",
            suggested_chain=Chain.TRON,
        )
    # Accept an uppercase '0X' prefix and normalise it. The EIP-55 checksum covers only the
    # 40-character body, so the prefix's case carries no information — but rejecting it here
    # would turn a harmless paste variation into a false negative.
    if raw[:2] in {"0X", "0x"}:
        raw = "0x" + raw[2:]
    else:
        return AddressValidation(
            valid=False,
            chain=Chain.ETHEREUM,
            error_code=AddressErrorCode.INVALID_CHARSET,
            error_message="An Ethereum address must start with '0x'.",
        )
    if len(raw) != 42:
        return AddressValidation(
            valid=False,
            chain=Chain.ETHEREUM,
            error_code=AddressErrorCode.INVALID_LENGTH,
            error_message=(
                f"An Ethereum address is 42 characters including '0x'; this one is {len(raw)}."
            ),
        )
    if not _ETH_RE.match(raw):
        return AddressValidation(
            valid=False,
            chain=Chain.ETHEREUM,
            error_code=AddressErrorCode.INVALID_CHARSET,
            error_message="An Ethereum address may contain only hexadecimal characters.",
        )

    body = raw[2:]
    is_mixed_case = body != body.lower() and body != body.upper()
    if is_mixed_case and not is_eip55_checksum_valid(raw):
        # Mixed case encodes a checksum, so a mismatch means the address was mistyped or
        # altered. Rejecting here prevents a wasted provider call on a wrong address.
        return AddressValidation(
            valid=False,
            chain=Chain.ETHEREUM,
            checksum_valid=False,
            error_code=AddressErrorCode.CHECKSUM_MISMATCH,
            error_message=(
                "The EIP-55 checksum does not match. Check the address for a typo, or paste "
                "it in all-lowercase to skip the checksum test."
            ),
        )

    canonical = raw.lower()
    return AddressValidation(
        valid=True,
        chain=Chain.ETHEREUM,
        canonical_address=canonical,
        display_address=to_eip55(canonical),
        checksum_valid=True if is_mixed_case else None,
        normalization_note=(
            None
            if is_mixed_case
            else "Address had no mixed-case checksum, so no checksum verification was possible."
        ),
    )


# ─── Tron ───────────────────────────────────────────────────────────────────────


def tron_hex_to_base58(hex_address: str) -> str:
    body = hex_address[2:] if hex_address.startswith("0x") else hex_address
    return b58check_encode(bytes.fromhex(body))


def tron_base58_to_hex(address: str) -> str:
    return b58check_decode(address).hex()


def _validate_tron(raw: str) -> AddressValidation:
    if _ETH_RE.match(raw):
        return AddressValidation(
            valid=False,
            chain=Chain.TRON,
            error_code=AddressErrorCode.WRONG_CHAIN_FORMAT,
            error_message="This looks like an Ethereum address. Select Ethereum instead.",
            suggested_chain=Chain.ETHEREUM,
        )

    note: str | None = None
    if _TRON_HEX_RE.match(raw):
        # Providers differ on which form they return; accept hex and convert it.
        raw = tron_hex_to_base58(raw)
        note = "Converted from Tron hex (41…) form to the canonical base58check T… form."

    if not raw.startswith("T"):
        return AddressValidation(
            valid=False,
            chain=Chain.TRON,
            error_code=AddressErrorCode.INVALID_CHARSET,
            error_message="A Tron address must start with 'T'.",
        )
    if len(raw) != 34:
        return AddressValidation(
            valid=False,
            chain=Chain.TRON,
            error_code=AddressErrorCode.INVALID_LENGTH,
            error_message=f"A Tron address is 34 characters; this one is {len(raw)}.",
        )

    try:
        payload = b58check_decode(raw)
    except ValueError:
        return AddressValidation(
            valid=False,
            chain=Chain.TRON,
            checksum_valid=False,
            error_code=AddressErrorCode.INVALID_BASE58_CHECKSUM,
            error_message="The address checksum does not match. Check the address for a typo.",
        )

    if len(payload) != 21 or payload[0] != TRON_ADDRESS_PREFIX:
        return AddressValidation(
            valid=False,
            chain=Chain.TRON,
            error_code=AddressErrorCode.INVALID_CHARSET,
            error_message="The address does not decode to a Tron mainnet address.",
        )

    # Tron's base58check form is already unambiguous, so it is its own canonical form.
    return AddressValidation(
        valid=True,
        chain=Chain.TRON,
        canonical_address=raw,
        display_address=raw,
        checksum_valid=True,
        normalization_note=note,
    )


# ─── public API ─────────────────────────────────────────────────────────────────

_VALIDATORS = {Chain.ETHEREUM: _validate_ethereum, Chain.TRON: _validate_tron}


def validate_address(address: str, chain: Chain) -> AddressValidation:
    """Validate ``address`` for ``chain``, returning a canonical form when it is valid."""
    raw = address.strip()
    if not raw:
        return AddressValidation(
            valid=False,
            chain=chain,
            error_code=AddressErrorCode.EMPTY,
            error_message="Enter a wallet address.",
        )

    validator = _VALIDATORS.get(chain)
    if validator is None:
        return AddressValidation(
            valid=False,
            chain=chain,
            error_code=AddressErrorCode.CHAIN_NOT_SUPPORTED,
            error_message=(f"{chain.value} is not supported yet. Ethereum and Tron are available."),
        )
    return validator(raw)


def canonicalize(address: str, chain: Chain) -> str:
    """Canonical form of a known-valid address.

    Raises ``ValueError`` when the address is invalid — callers that can present an error to
    a user should use :func:`validate_address` instead and read the error code.
    """
    result = validate_address(address, chain)
    if not result.valid or result.canonical_address is None:
        raise ValueError(result.error_message or "invalid address")
    return result.canonical_address
