"""Observation store: idempotency, exact decimals, and snapshot pinning."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.blockchain.base import NormalizedTx
from app.database.models import (
    ApiResponseCache,
    LabelDatasetVersion,
    TokenTransfer,
    Trace,
    Transaction,
    Wallet,
)
from app.database.repositories import observations as obs
from app.schemas.common import Chain, DataProvenance, TxKind, TxStatus

A = "0x" + "a" * 40
B = "0x" + "b" * 40
C = "0x" + "c" * 40
T0 = datetime(2026, 8, 1, 12, 0, tzinfo=UTC)


def tx(
    *,
    tx_hash: str = "0xhash1",
    sender: str = A,
    recipient: str = B,
    amount: str = "1.5",
    symbol: str = "ETH",
    kind: TxKind = TxKind.NATIVE,
    decimals: int = 18,
    log_index: int | None = None,
    contract: str | None = None,
    minutes: int = 0,
) -> NormalizedTx:
    scale = Decimal(10) ** decimals
    value = Decimal(amount)
    return NormalizedTx(
        chain=Chain.ETHEREUM,
        tx_hash=tx_hash,
        block_timestamp=T0 + timedelta(minutes=minutes),
        from_address=sender,
        to_address=recipient,
        asset_symbol=symbol,
        amount=value,
        amount_raw=str(int(value * scale)),
        decimals=decimals,
        kind=kind,
        status=TxStatus.SUCCESS,
        provenance=DataProvenance.LIVE_API,
        asset_contract=contract,
        log_index=log_index,
    )


async def count(session: AsyncSession, model: type) -> int:
    return await session.scalar(select(func.count()).select_from(model)) or 0


class TestIdempotency:
    async def test_re_ingesting_a_page_inserts_nothing_new(self, db_session: AsyncSession) -> None:
        """A trace re-runs queries earlier traces already made; duplicates would inflate
        the observed-activity counts that feed the fan-in/fan-out heuristics."""
        page = [tx(), tx(tx_hash="0xhash2", recipient=C, minutes=10)]

        first = await obs.persist_page(db_session, Chain.ETHEREUM, page)
        assert first.transactions_inserted == 2
        assert first.transactions_skipped == 0

        second = await obs.persist_page(db_session, Chain.ETHEREUM, page)
        assert second.transactions_inserted == 0
        assert second.transactions_skipped == 2

        assert await count(db_session, Transaction) == 2

    async def test_duplicates_within_one_batch_are_collapsed(
        self, db_session: AsyncSession
    ) -> None:
        """A merged native+internal page can repeat the same edge."""
        result = await obs.persist_transactions(db_session, [tx(), tx(), tx()])
        assert result.transactions_inserted == 1
        assert await count(db_session, Transaction) == 1

    async def test_one_hash_moving_two_assets_is_two_rows(self, db_session: AsyncSession) -> None:
        await obs.persist_transactions(
            db_session,
            [
                tx(tx_hash="0xsame"),
                tx(tx_hash="0xsame", symbol="WETH"),
                tx(tx_hash="0xsame", kind=TxKind.INTERNAL),
            ],
        )
        assert await count(db_session, Transaction) == 3

    async def test_token_transfers_dedup_on_log_index(self, db_session: AsyncSession) -> None:
        page = [
            tx(kind=TxKind.TOKEN, symbol="USDT", decimals=6, log_index=1, contract=C),
            tx(kind=TxKind.TOKEN, symbol="USDT", decimals=6, log_index=2, contract=C),
        ]
        first = await obs.persist_transactions(db_session, page)
        assert first.token_transfers_inserted == 2

        second = await obs.persist_transactions(db_session, page)
        assert second.token_transfers_skipped == 2
        assert await count(db_session, TokenTransfer) == 2

    async def test_a_missing_log_index_still_dedups(self, db_session: AsyncSession) -> None:
        """NULLs never compare equal in a unique constraint, so it is stored as -1."""
        record = tx(kind=TxKind.TOKEN, symbol="USDT", decimals=6, log_index=None, contract=C)

        await obs.persist_transactions(db_session, [record])
        again = await obs.persist_transactions(db_session, [record])

        assert again.token_transfers_skipped == 1
        assert await count(db_session, TokenTransfer) == 1
        row = (await db_session.execute(select(TokenTransfer))).scalar_one()
        assert row.log_index == -1

    async def test_native_and_token_go_to_their_own_tables(self, db_session: AsyncSession) -> None:
        await obs.persist_transactions(
            db_session,
            [tx(), tx(kind=TxKind.TOKEN, symbol="USDT", decimals=6, log_index=0, contract=C)],
        )
        assert await count(db_session, Transaction) == 1
        assert await count(db_session, TokenTransfer) == 1


class TestExactAmounts:
    @pytest.mark.parametrize(
        ("amount", "decimals"),
        [
            ("1234.567890123456789012", 18),  # every one of 18 decimal places significant
            ("0.000000000000000001", 18),  # one wei
            ("48250.123456", 6),  # USDT
            ("99999999999999999999.5", 18),  # large magnitude
        ],
    )
    async def test_amounts_round_trip_exactly(
        self, db_session: AsyncSession, amount: str, decimals: int
    ) -> None:
        """A report is evidentiary output; it must show the amount that actually moved."""
        record = tx(amount=amount, decimals=decimals)
        await obs.persist_transactions(db_session, [record])

        row = (await db_session.execute(select(Transaction))).scalar_one()
        assert row.amount == Decimal(amount)
        assert row.amount_raw == record.amount_raw
        # And the two representations still agree after the round trip.
        assert str(int(row.amount * (Decimal(10) ** row.decimals))) == row.amount_raw

    @pytest.mark.parametrize(
        ("amount", "expected"),
        [
            # Decimal's own repr would render this as "1E-18" — correct, but unreadable on
            # an evidence table and easy to misread as a different magnitude.
            ("0.000000000000000001", "0.000000000000000001"),
            ("1.5", "1.5"),
            ("1234.567890123456789012", "1234.567890123456789012"),
            ("0", "0"),
        ],
    )
    async def test_amounts_render_in_plain_notation(
        self, db_session: AsyncSession, amount: str, expected: str
    ) -> None:
        from app.database.types import format_amount

        await obs.persist_transactions(db_session, [tx(amount=amount or "1")])
        row = (await db_session.execute(select(Transaction))).scalar_one()

        rendered = format_amount(row.amount if amount != "0" else Decimal("0"))
        assert rendered == expected
        assert "E" not in (rendered or "").upper()


class TestWallets:
    async def test_every_address_seen_is_recorded_once(self, db_session: AsyncSession) -> None:
        await obs.persist_page(
            db_session,
            Chain.ETHEREUM,
            [tx(), tx(tx_hash="0x2", sender=B, recipient=C, minutes=5)],
        )
        assert await count(db_session, Wallet) == 3  # A, B, C

    async def test_activity_window_spans_every_observation(self, db_session: AsyncSession) -> None:
        await obs.persist_page(
            db_session,
            Chain.ETHEREUM,
            [
                tx(tx_hash="0x1", minutes=100),
                tx(tx_hash="0x2", minutes=0),
                tx(tx_hash="0x3", minutes=50),
            ],
        )
        row = (await db_session.execute(select(Wallet).where(Wallet.address == A))).scalar_one()

        assert row.first_seen_at is not None and row.last_seen_at is not None
        assert obs._aware(row.first_seen_at) == T0
        assert obs._aware(row.last_seen_at) == T0 + timedelta(minutes=100)

    async def test_re_ingesting_does_not_inflate_the_observed_count(
        self, db_session: AsyncSession
    ) -> None:
        """This count feeds fan-in/fan-out risk heuristics, so double-counting would
        manufacture a risk indicator out of a repeated query."""
        page = [tx(), tx(tx_hash="0x2", minutes=5)]

        await obs.persist_page(db_session, Chain.ETHEREUM, page)
        first = (await db_session.execute(select(Wallet).where(Wallet.address == A))).scalar_one()
        assert first.tx_count_observed == 2

        await obs.persist_page(db_session, Chain.ETHEREUM, page)
        again = (await db_session.execute(select(Wallet).where(Wallet.address == A))).scalar_one()
        assert again.tx_count_observed == 2

    async def test_the_same_address_on_two_chains_is_two_rows(
        self, db_session: AsyncSession
    ) -> None:
        await obs.persist_page(db_session, Chain.ETHEREUM, [tx()])
        await obs.upsert_wallets(db_session, Chain.TRON, [tx()])
        assert await count(db_session, Wallet) == 4  # A,B on ethereum + A,B on tron

    async def test_an_empty_page_is_a_no_op(self, db_session: AsyncSession) -> None:
        assert await obs.upsert_wallets(db_session, Chain.ETHEREUM, []) == (0, 0)
        result = await obs.persist_transactions(db_session, [])
        assert result.total_inserted == 0


class TestSnapshots:
    async def _cache_row(
        self, session: AsyncSession, key: str, *, expires_in: int | None = 900
    ) -> ApiResponseCache:
        row = ApiResponseCache(
            cache_key=key,
            chain="ethereum",
            provider="etherscan",
            endpoint="",
            request_params={"module": "account"},
            response_body={"result": []},
            http_status=200,
            expires_at=(
                datetime.now(UTC) + timedelta(seconds=expires_in)
                if expires_in is not None
                else None
            ),
        )
        session.add(row)
        await session.flush()
        return row

    async def _trace(self, session: AsyncSession) -> Trace:
        version = LabelDatasetVersion(version=f"v-{uuid.uuid4().hex[:6]}", source_manifest={})
        session.add(version)
        await session.flush()
        trace = Trace(
            subject_address=A,
            subject_address_input=A,
            chain="ethereum",
            hop_depth=3,
            status="completed",
            data_provenance="live_api",
            label_dataset_version_id=version.id,
            scoring_config_version="sc-v1",
            budget_config={},
            engine_version="0.1.0",
        )
        session.add(trace)
        await session.flush()
        return trace

    async def test_pinning_marks_rows_as_never_expiring(self, db_session: AsyncSession) -> None:
        """Without this, the cache behind a report expires and the report can never be
        regenerated or explained again (DPRD sec.15)."""
        trace = await self._trace(db_session)
        row = await self._cache_row(db_session, "k1")
        assert row.expires_at is not None

        assert await obs.pin_snapshots(db_session, trace.id, [row.id]) == 1
        await db_session.refresh(row)

        assert row.is_snapshot is True
        assert row.expires_at is None

    async def test_pinning_is_idempotent(self, db_session: AsyncSession) -> None:
        trace = await self._trace(db_session)
        row = await self._cache_row(db_session, "k1")

        assert await obs.pin_snapshots(db_session, trace.id, [row.id]) == 1
        assert await obs.pin_snapshots(db_session, trace.id, [row.id]) == 0

        assert await obs.snapshot_ids_for_trace(db_session, trace.id) == [row.id]

    async def test_a_pinned_row_survives_eviction(self, db_session: AsyncSession) -> None:
        trace = await self._trace(db_session)
        pinned = await self._cache_row(db_session, "pinned", expires_in=-10)
        expired = await self._cache_row(db_session, "expired", expires_in=-10)
        await self._cache_row(db_session, "fresh", expires_in=900)

        await obs.pin_snapshots(db_session, trace.id, [pinned.id])
        removed = await obs.evict_expired_cache(db_session)

        assert removed == 1
        remaining = set(
            (await db_session.execute(select(ApiResponseCache.cache_key))).scalars().all()
        )
        assert remaining == {"pinned", "fresh"}
        assert expired.cache_key not in remaining

    async def test_pinning_nothing_is_a_no_op(self, db_session: AsyncSession) -> None:
        trace = await self._trace(db_session)
        assert await obs.pin_snapshots(db_session, trace.id, []) == 0


class TestRawRefLinkage:
    async def test_a_transaction_can_cite_the_response_that_produced_it(
        self, db_session: AsyncSession
    ) -> None:
        row = ApiResponseCache(
            cache_key="k",
            chain="ethereum",
            provider="etherscan",
            endpoint="",
            request_params={},
            response_body={},
            http_status=200,
        )
        db_session.add(row)
        await db_session.flush()

        await obs.persist_transactions(db_session, [tx()], raw_ref=row.id)

        stored = (await db_session.execute(select(Transaction))).scalar_one()
        assert stored.raw_ref == row.id
