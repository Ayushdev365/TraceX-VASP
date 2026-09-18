"""Tron adapter over the TronGrid v1 API.

Tron matters most of the two MVP chains: TRC-20 USDT is the dominant cash-out rail for the
South/Southeast Asian scam ecosystems that generate Indian cybercrime cases (DPRD sec.11), so
token transfers here are the primary signal rather than a secondary one.

TronGrid differs from Etherscan in ways that shape this file:

* **Two unrelated response shapes.** Native TRX transfers arrive as deeply nested
  ``raw_data.contract[].parameter.value`` objects; TRC-20 transfers arrive pre-flattened.
* **Addresses come back in both forms.** The raw transaction endpoint returns hex ``41…``,
  the TRC-20 endpoint returns base58 ``T…``. Both are canonicalised on the way in, or label
  matching would silently miss (DPRD sec.17).
* **Timestamps are milliseconds**, not seconds. Reading them as seconds would place every
  transaction in 1970 and destroy the temporal-consistency scoring factor.
* **Paging is by opaque ``fingerprint``**, not page number.
* **Success is ``ret[0].contractRet == "SUCCESS"``**; anything else means the value did not
  move.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.blockchain.addresses import AddressValidation, validate_address
from app.blockchain.base import NormalizedTx, Page
from app.blockchain.http import ProviderClient
from app.config import get_settings
from app.core.errors import InvalidAddress, UpstreamProviderError
from app.core.logging import get_logger
from app.schemas.common import Chain, DataProvenance, Direction, TxKind, TxStatus

logger = get_logger(__name__)

TRX_DECIMALS = 6  # TRX is denominated in "sun"
TRX_SYMBOL = "TRX"

#: The only contract type that moves TRX between accounts. Others (votes, contract calls
#: without value, resource freezing) carry no traceable transfer.
TRANSFER_CONTRACT = "TransferContract"


def _canonical(address: str | None) -> str:
    """Canonicalise a Tron address in either hex or base58 form; '' if unusable."""
    if not address:
        return ""
    result = validate_address(address.strip(), Chain.TRON)
    return result.canonical_address or ""


def _amount(raw: Any, decimals: int) -> tuple[Decimal, str]:
    try:
        base_units = int(str(raw if raw is not None else "0").strip() or "0")
    except ValueError:
        return Decimal(0), "0"
    return Decimal(base_units) / (Decimal(10) ** decimals), str(base_units)


def _timestamp_ms(raw: Any) -> datetime:
    """TronGrid reports milliseconds since epoch."""
    try:
        return datetime.fromtimestamp(int(str(raw or 0)) / 1000, tz=UTC)
    except (ValueError, OSError, OverflowError):
        return datetime.fromtimestamp(0, tz=UTC)


class TronAdapter:
    """Implements :class:`app.blockchain.base.ChainAdapter` for Tron mainnet."""

    chain = Chain.TRON
    native_asset = TRX_SYMBOL
    provenance = DataProvenance.LIVE_API

    def __init__(self, *, session: AsyncSession | None = None, api_key: str | None = None) -> None:
        settings = get_settings()
        self._api_key = api_key if api_key is not None else settings.trongrid_api_key
        self._client = ProviderClient(
            "trongrid",
            settings.trongrid_base_url,
            chain=Chain.TRON,
            rate_per_second=4.0,
            session=session,
        )

    # ─── contract: validation ───────────────────────────────────────────────

    def validate_address(self, address: str) -> AddressValidation:
        return validate_address(address, Chain.TRON)

    def _require_canonical(self, address: str) -> str:
        result = self.validate_address(address)
        if not result.valid or result.canonical_address is None:
            raise InvalidAddress(
                result.error_message or "The address is not a valid Tron address.",
                details={"code": result.error_code.value if result.error_code else None},
            )
        return result.canonical_address

    # ─── contract: fetching ─────────────────────────────────────────────────

    async def _query(
        self, path: str, params: dict[str, Any], *, force_refresh: bool
    ) -> tuple[list[dict[str, Any]], str | None, DataProvenance, int]:
        """Return ``(records, next_fingerprint, provenance, api_calls)``."""
        response = await self._client.get_json(
            path,
            params,
            secret_headers={"TRON-PRO-API-KEY": self._api_key} if self._api_key else None,
            force_refresh=force_refresh,
        )
        body = response.body

        if body.get("success") is False:
            logger.warning("trongrid_unsuccessful", extra={"path": path})
            raise UpstreamProviderError(
                "The Tron data provider rejected the request.",
                details={"provider": "trongrid"},
            )

        records = body.get("data")
        if not isinstance(records, list):
            raise UpstreamProviderError(
                "The Tron data provider returned an unexpected response.",
                details={"provider": "trongrid", "path": path},
            )

        raw_meta = body.get("meta")
        meta: dict[str, Any] = raw_meta if isinstance(raw_meta, dict) else {}
        # A fingerprint is only a real cursor when the provider also offers a next page link;
        # TronGrid returns one on the final page too, which would loop forever.
        fingerprint = (
            str(meta["fingerprint"]) if meta.get("links") and meta.get("fingerprint") else None
        )

        return records, fingerprint, response.provenance, response.api_calls

    async def get_wallet_transactions(
        self,
        address: str,
        *,
        direction: Direction = Direction.OUT,
        limit: int = 200,
        cursor: str | None = None,
        force_refresh: bool = False,
    ) -> Page:
        """Native TRX transfers."""
        canonical = self._require_canonical(address)
        page_size = max(1, min(limit, get_settings().max_txs_per_address))

        params: dict[str, Any] = {"limit": page_size, "order_by": "block_timestamp,desc"}
        if cursor:
            params["fingerprint"] = cursor
        # Let the provider filter by direction where it can; results are re-checked below.
        params["only_to" if direction is Direction.IN else "only_from"] = "true"

        records, fingerprint, provenance, calls = await self._query(
            f"v1/accounts/{canonical}/transactions", params, force_refresh=force_refresh
        )

        normalized = tuple(
            tx
            for tx in (self.normalize_transaction(record) for record in records)
            if tx is not None and self._matches(tx, canonical, direction)
        )
        return Page(
            transactions=normalized,
            next_cursor=fingerprint,
            complete=True,
            provenance=provenance,
            api_calls=calls,
        )

    async def get_token_transfers(
        self,
        address: str,
        *,
        direction: Direction = Direction.OUT,
        limit: int = 200,
        cursor: str | None = None,
        force_refresh: bool = False,
    ) -> Page:
        """TRC-20 transfers — the dominant rail on this chain (DPRD sec.11)."""
        canonical = self._require_canonical(address)
        page_size = max(1, min(limit, get_settings().max_txs_per_address))

        params: dict[str, Any] = {"limit": page_size, "order_by": "block_timestamp,desc"}
        if cursor:
            params["fingerprint"] = cursor
        params["only_to" if direction is Direction.IN else "only_from"] = "true"

        records, fingerprint, provenance, calls = await self._query(
            f"v1/accounts/{canonical}/transactions/trc20", params, force_refresh=force_refresh
        )

        normalized = tuple(
            tx
            for tx in (self._normalize_trc20(record) for record in records)
            if tx is not None and self._matches(tx, canonical, direction)
        )
        return Page(
            transactions=normalized,
            next_cursor=fingerprint,
            complete=True,
            provenance=provenance,
            api_calls=calls,
        )

    async def get_transaction(self, tx_hash: str) -> NormalizedTx | None:
        records, _fingerprint, _provenance, _calls = await self._query(
            "v1/transactions", {"hash": tx_hash}, force_refresh=False
        )
        for record in records:
            tx = self.normalize_transaction(record)
            if tx is not None:
                return tx
        return None

    @staticmethod
    def _matches(tx: NormalizedTx, canonical: str, direction: Direction) -> bool:
        if direction is Direction.OUT:
            return tx.from_address == canonical
        return tx.to_address == canonical

    # ─── contract: normalization ────────────────────────────────────────────

    def normalize_transaction(self, raw: dict[str, Any]) -> NormalizedTx | None:
        """Normalise a native TRX transaction from the nested v1 shape.

        TRC-20 records use a different shape entirely; they go through
        :meth:`_normalize_trc20`. Both produce the same ``NormalizedTx``.
        """
        # A pre-flattened TRC-20 record can reach here via get_transaction; route it.
        if "token_info" in raw:
            return self._normalize_trc20(raw)

        tx_hash = str(raw.get("txID") or "").strip().lower()
        if not tx_hash:
            return None

        contracts = (raw.get("raw_data") or {}).get("contract") or []
        if not contracts or not isinstance(contracts[0], dict):
            return None
        contract: dict[str, Any] = contracts[0]
        if contract.get("type") != TRANSFER_CONTRACT:
            # Votes, resource freezing and value-less contract calls move nothing traceable.
            return None

        value = ((contract.get("parameter") or {}).get("value")) or {}
        from_address = _canonical(value.get("owner_address"))
        to_address = _canonical(value.get("to_address"))
        if not from_address or not to_address:
            return None

        amount, amount_raw = _amount(value.get("amount"), TRX_DECIMALS)
        if amount == 0:
            return None

        ret = raw.get("ret") or []
        result = (ret[0].get("contractRet") if ret and isinstance(ret[0], dict) else "") or ""
        failed = result.upper() != "SUCCESS"

        fee: Decimal | None = None
        if raw.get("fee") not in (None, ""):
            fee, _ = _amount(raw.get("fee"), TRX_DECIMALS)

        return NormalizedTx(
            chain=Chain.TRON,
            tx_hash=tx_hash,
            block_timestamp=_timestamp_ms(raw.get("block_timestamp")),
            block_number=int(raw["blockNumber"])
            if str(raw.get("blockNumber") or "").isdigit()
            else None,
            from_address=from_address,
            to_address=to_address,
            asset_symbol=TRX_SYMBOL,
            amount=amount,
            amount_raw=amount_raw,
            decimals=TRX_DECIMALS,
            kind=TxKind.NATIVE,
            status=TxStatus.FAILED if failed else TxStatus.SUCCESS,
            provenance=self.provenance,
            fee=fee,
        )

    def _normalize_trc20(self, raw: dict[str, Any]) -> NormalizedTx | None:
        tx_hash = str(raw.get("transaction_id") or raw.get("txID") or "").strip().lower()
        from_address = _canonical(raw.get("from"))
        to_address = _canonical(raw.get("to"))
        if not tx_hash or not from_address or not to_address:
            return None

        token = raw.get("token_info") or {}
        try:
            decimals = int(str(token.get("decimals", TRX_DECIMALS)))
        except ValueError:
            decimals = TRX_DECIMALS
        symbol = str(token.get("symbol") or "UNKNOWN").strip() or "UNKNOWN"

        amount, amount_raw = _amount(raw.get("value"), decimals)
        if amount == 0:
            return None

        return NormalizedTx(
            chain=Chain.TRON,
            tx_hash=tx_hash,
            block_timestamp=_timestamp_ms(raw.get("block_timestamp")),
            from_address=from_address,
            to_address=to_address,
            asset_symbol=symbol,
            amount=amount,
            amount_raw=amount_raw,
            decimals=decimals,
            kind=TxKind.TOKEN,
            # The TRC-20 endpoint only lists transfers that actually occurred.
            status=TxStatus.SUCCESS,
            provenance=self.provenance,
            asset_contract=_canonical(token.get("address")) or None,
        )
