"""Address validation request/response models (API contract sec.4)."""

from __future__ import annotations

from pydantic import Field

from app.schemas.common import ApiModel, Chain


class AddressValidationRequest(ApiModel):
    address: str = Field(min_length=1, max_length=128)
    chain: Chain


class AddressValidationResponse(ApiModel):
    valid: bool
    chain: Chain
    canonical_address: str | None = None
    display_address: str | None = None
    #: ``None`` when the input carried no checksum information — never defaulted to true.
    checksum_valid: bool | None = None
    normalization_note: str | None = None
    error_code: str | None = None
    error_message: str | None = None
    #: Set when the address looks valid for a *different* chain.
    suggested_chain: Chain | None = None
