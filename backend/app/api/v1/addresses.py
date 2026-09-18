"""Address validation endpoint.

Validating before a trace is a cost guard as much as a correctness one: a malformed address
would otherwise burn provider quota and return an empty result that looks like "this wallet
has no activity" (DPRD sec.17).
"""

from __future__ import annotations

from fastapi import APIRouter

from app.blockchain.addresses import validate_address
from app.deps import RequireApiKey
from app.schemas.address import AddressValidationRequest, AddressValidationResponse

router = APIRouter(tags=["addresses"], dependencies=[RequireApiKey])


@router.post(
    "/addresses/validate",
    response_model=AddressValidationResponse,
    summary="Validate a wallet address for a blockchain",
)
async def validate(request: AddressValidationRequest) -> AddressValidationResponse:
    """Validate and canonicalise an address.

    Returns 200 with ``valid: false`` for a bad address rather than an error status: this is
    a form-field check the UI calls as the investigator types, and a rejection is a normal
    outcome, not a failure.
    """
    result = validate_address(request.address, request.chain)
    return AddressValidationResponse(
        valid=result.valid,
        chain=result.chain,
        canonical_address=result.canonical_address,
        display_address=result.display_address,
        checksum_valid=result.checksum_valid,
        normalization_note=result.normalization_note,
        error_code=result.error_code.value if result.error_code else None,
        error_message=result.error_message,
        suggested_chain=result.suggested_chain,
    )
