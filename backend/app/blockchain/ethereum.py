"""Ethereum adapter over the Etherscan-compatible V2 API.

Three record types are fetched and normalised into one schema:

* ``txlist`` — native ETH transfers.
* ``txlistinternal`` — value moved by contract execution. Skipping these loses real fund
  flow: a wallet can send ETH to an exchange entirely through a contract call, and the trace
  would show nothing.
* ``tokentx`` — ERC-20 transfers.

Etherscan's quirks that shape this code:

* Errors arrive as HTTP 200 with ``status: "0"``. "No transactions found" is one of them and
  is an empty result, not a failure.
* Rate-limit rejection also arrives as HTTP 200, with a message in ``result``.
* A single query returns at most 10 000 records regardless of paging, so a wallet busier
  than that is reported as incomplete rather than silently truncated (DPRD sec.17).
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
from app.core.errors import InvalidAddress, UpstreamProviderError, UpstreamRateLimited
from app.core.logging import get_logger
from app.schemas.common import Chain, DataProvenance, Direction, TxKind, TxStatus

logger = get_logger(__name__)

ETH_DECIMALS = 18
ETH_SYMBOL = "ETH"
MAINNET_CHAIN_ID = 1

#: Etherscan caps any single query at 10 000 records however you page it.
PROVIDER_RECORD_CAP = 10_000

#: Returned as an ordinary 200 body; means "no results", not "error".
_EMPTY_MESSAGES = ("no transactions found", "no records found")
_RATE_LIMIT_MARKERS = ("rate limit", "max rate limit reached", "too many")


def _to_decimal(raw: str | int | None, decimals: int) -> tuple[Decimal, str]:
    """Return ``(human_amount, exact_base_units)``. Exact integer arithmetic only."""
    text = str(raw if raw is not None else "0").strip() or "0"
    try:
        base_units = int(text)
    except ValueError:
        return Decimal(0), "0"
    return Decimal(base_units) / (Decimal(10) ** decimals), str(base_units)


def _timestamp(raw: str | int | None) -> datetime:
    try:
        return datetime.fromtimestamp(int(str(raw or 0)), tz=UTC)
    except (ValueError, OSError, OverflowError):
        return datetime.fromtimestamp(0, tz=UTC)


def _lower(value: str | None) -> str:
    return (value or "").strip().lower()


class EthereumAdapter:
    """Implements :class:`app.blockchain.base.ChainAdapter` for Ethereum mainnet."""

    chain = Chain.ETHEREUM
    native_asset = ETH_SYMBOL
    provenance = DataProvenance.LIVE_API

    def __init__(self, *, session: AsyncSession | None = None, api_key: str | None = None) -> None:
        settings = get_settings()
        self._api_key = api_key if api_key is not None else settings.etherscan_api_key
        self._client = ProviderClient(
            "etherscan",
            settings.etherscan_base_url,
            chain=Chain.ETHEREUM,
            # Free tier is 5 req/s; stay under it rather than relying on retries.
            rate_per_second=4.0,
            session=session,
        )

    # ─── contract: validation ───────────────────────────────────────────────

    def validate_address(self, address: str) -> AddressValidation:
        return validate_address(address, Chain.ETHEREUM)

    def _require_canonical(self, address: str) -> str:
        result = self.validate_address(address)
        if not result.valid or result.canonical_address is None:
            raise InvalidAddress(
                result.error_message or "The address is not a valid Ethereum address.",
                details={"code": result.error_code.value if result.error_code else None},
            )
        return result.canonical_address

    # ─── contract: fetching ─────────────────────────────────────────────────

    async def _query(
        self, action: str, params: dict[str, Any], *, force_refresh: bool = False
    ) -> tuple[list[dict[str, Any]], DataProvenance, int]:
        """Run one account query, returning ``(records, provenance, api_calls)``."""
        response = await self._client.get_json(
            "",
            {"chainid": MAINNET_CHAIN_ID, "module": "account", "action": action, **params},
            secret_params={"apikey": self._api_key} if self._api_key else None,
            force_refresh=force_refresh,
        )

        body = response.body
        status = str(body.get("status", "")).strip()
        message = str(body.get("message", "")).strip().lower()
        result = body.get("result")

        if status == "1" and isinstance(result, list):
            return result, response.provenance, response.api_calls

        if any(marker in message for marker in _EMPTY_MESSAGES):
            return [], response.provenance, response.api_calls

        # A rate-limit rejection can appear in either field, as an HTTP 200.
        haystack = f"{message} {result if isinstance(result, str) else ''}".lower()
        if any(marker in haystack for marker in _RATE_LIMIT_MARKERS):
            raise UpstreamRateLimited(
                "The Ethereum data provider's rate limit was reached. Please retry shortly.",
                details={"provider": "etherscan", "retry_after_s": 2},
            )

        if isinstance(result, list):
            return result, response.provenance, response.api_calls

        logger.warning("etherscan_unexpected_body", extra={"action": action, "status": status})
        raise UpstreamProviderError(
            "The Ethereum data provider returned an unexpected response.",
            details={"provider": "etherscan", "action": action},
        )

    async def _fetch(
        self,
        action: str,
        address: str,
        *,
        direction: Direction,
        limit: int,
        cursor: str | None,
        force_refresh: bool,
    ) -> Page:
        canonical = self._require_canonical(address)
        page_number = int(cursor) if cursor else 1
        page_size = max(1, min(limit, get_settings().max_txs_per_address))

        records, provenance, api_calls = await self._query(
            action,
            {
                "address": canonical,
                "startblock": 0,
                "endblock": 99_999_999,
                "page": page_number,
                "offset": page_size,
                # Newest first: a truncated trace then keeps the most recent activity, which
                # is what an investigator following live funds needs.
                "sort": "desc",
            },
            force_refresh=force_refresh,
        )

        normalized = tuple(
            tx
            for tx in (self.normalize_transaction(record) for record in records)
            if tx is not None and self._matches_direction(tx, canonical, direction)
        )

        full_page = len(records) >= page_size
        records_seen = page_number * page_size
        at_provider_cap = records_seen >= PROVIDER_RECORD_CAP

        return Page(
            transactions=normalized,
            next_cursor=str(page_number + 1) if full_page and not at_provider_cap else None,
            complete=not at_provider_cap,
            truncation_reason=(
                f"The provider caps a single query at {PROVIDER_RECORD_CAP:,} records; this "
                f"wallet's history may extend further back."
                if at_provider_cap
                else None
            ),
            provenance=provenance,
            api_calls=api_calls,
        )

    @staticmethod
    def _matches_direction(tx: NormalizedTx, canonical: str, direction: Direction) -> bool:
        if direction is Direction.OUT:
            return tx.from_address == canonical
        return tx.to_address == canonical

    async def get_wallet_transactions(
        self,
        address: str,
        *,
        direction: Direction = Direction.OUT,
        limit: int = 200,
        cursor: str | None = None,
        force_refresh: bool = False,
        include_internal: bool = True,
    ) -> Page:
        """Native ETH transfers, including value moved by contract execution."""
        external = await self._fetch(
            "txlist",
            address,
            direction=direction,
            limit=limit,
            cursor=cursor,
            force_refresh=force_refresh,
        )
        if not include_internal:
            return external

        internal = await self._fetch(
            "txlistinternal",
            address,
            direction=direction,
            limit=limit,
            cursor=cursor,
            force_refresh=force_refresh,
        )

        # Merge, dedup, and keep newest first so a caller that trims still holds the most
        # recent flow.
        merged: dict[str, NormalizedTx] = {}
        for tx in (*external.transactions, *internal.transactions):
            merged.setdefault(tx.dedup_key, tx)
        ordered = tuple(sorted(merged.values(), key=lambda tx: tx.block_timestamp, reverse=True))

        return Page(
            transactions=ordered,
            next_cursor=external.next_cursor or internal.next_cursor,
            complete=external.complete and internal.complete,
            truncation_reason=external.truncation_reason or internal.truncation_reason,
            provenance=_merge_provenance(external.provenance, internal.provenance),
            api_calls=external.api_calls + internal.api_calls,
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
        return await self._fetch(
            "tokentx",
            address,
            direction=direction,
            limit=limit,
            cursor=cursor,
            force_refresh=force_refresh,
        )

    async def get_transaction(self, tx_hash: str) -> NormalizedTx | None:
        """Look up one transaction by hash via ``eth_getTransactionByHash``."""
        response = await self._client.get_json(
            "",
            {
                "chainid": MAINNET_CHAIN_ID,
                "module": "proxy",
                "action": "eth_getTransactionByHash",
                "txhash": tx_hash,
            },
            secret_params={"apikey": self._api_key} if self._api_key else None,
        )
        result = response.body.get("result")
        if not isinstance(result, dict) or not result.get("hash"):
            return None

        amount, raw = _to_decimal(int(str(result.get("value", "0x0")), 16), ETH_DECIMALS)
        return NormalizedTx(
            chain=Chain.ETHEREUM,
            tx_hash=_lower(result.get("hash")),
            # The proxy endpoint carries no timestamp; the block would need a second call,
            # so callers that need ordering should use the list endpoints.
            block_timestamp=datetime.fromtimestamp(0, tz=UTC),
            block_number=(
                int(str(result["blockNumber"]), 16) if result.get("blockNumber") else None
            ),
            from_address=_lower(result.get("from")),
            to_address=_lower(result.get("to")),
            asset_symbol=ETH_SYMBOL,
            amount=amount,
            amount_raw=raw,
            decimals=ETH_DECIMALS,
            kind=TxKind.NATIVE,
            status=TxStatus.SUCCESS,
            provenance=response.provenance,
        )

    # ─── contract: normalization ────────────────────────────────────────────

    def normalize_transaction(self, raw: dict[str, Any]) -> NormalizedTx | None:
        """Map one Etherscan record onto ``NormalizedTx``.

        Returns ``None`` for records that carry no traceable value movement — contract
        creations with no recipient, and zero-value calls. Keeping those would inflate the
        graph with edges that move nothing.
        """
        tx_hash = _lower(raw.get("hash"))
        to_address = _lower(raw.get("to"))
        from_address = _lower(raw.get("from"))
        if not tx_hash or not to_address or not from_address:
            return None

        is_token = bool(raw.get("tokenSymbol") or raw.get("tokenDecimal"))
        if is_token:
            try:
                decimals = int(str(raw.get("tokenDecimal") or ETH_DECIMALS))
            except ValueError:
                decimals = ETH_DECIMALS
            symbol = str(raw.get("tokenSymbol") or "UNKNOWN").strip() or "UNKNOWN"
            contract = _lower(raw.get("contractAddress")) or None
            kind = TxKind.TOKEN
        else:
            decimals, symbol, contract = ETH_DECIMALS, ETH_SYMBOL, None
            # 'type' is present only on internal records ("call", "delegatecall", ...).
            kind = TxKind.INTERNAL if raw.get("type") else TxKind.NATIVE

        amount, amount_raw = _to_decimal(raw.get("value"), decimals)
        if amount == 0:
            return None

        # Failure is signalled differently per record type; both mean the value did not move.
        is_error = str(raw.get("isError", "0")) == "1"
        receipt = str(raw.get("txreceipt_status", "")).strip()
        failed = is_error or receipt == "0"

        fee: Decimal | None = None
        gas_used, gas_price = raw.get("gasUsed"), raw.get("gasPrice")
        if gas_used and gas_price:
            try:
                fee = Decimal(int(str(gas_used)) * int(str(gas_price))) / (
                    Decimal(10) ** ETH_DECIMALS
                )
            except ValueError:
                fee = None

        log_index: int | None = None
        if raw.get("logIndex") not in (None, ""):
            try:
                log_index = int(str(raw["logIndex"]))
            except ValueError:
                log_index = None

        return NormalizedTx(
            chain=Chain.ETHEREUM,
            tx_hash=tx_hash,
            block_timestamp=_timestamp(raw.get("timeStamp")),
            block_number=int(str(raw["blockNumber"])) if raw.get("blockNumber") else None,
            from_address=from_address,
            to_address=to_address,
            asset_symbol=symbol,
            amount=amount,
            amount_raw=amount_raw,
            decimals=decimals,
            kind=kind,
            status=TxStatus.FAILED if failed else TxStatus.SUCCESS,
            provenance=self.provenance,
            asset_contract=contract,
            log_index=log_index,
            fee=fee,
        )


def _merge_provenance(*values: DataProvenance) -> DataProvenance:
    distinct = set(values)
    if len(distinct) == 1:
        return next(iter(distinct))
    return DataProvenance.MIXED
