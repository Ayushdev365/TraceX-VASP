"""Mock chain adapter — clearly-labelled synthetic data.

Purpose: let Phases 6-9 be developed and demonstrated without provider keys or network, and
give the demo an offline fallback if the venue Wi-Fi fails (DPRD sec.28 contingency).

The honesty rules are structural, not advisory:

* ``provenance`` is always ``MOCK_DEMO``. It propagates into every ``NormalizedTx``, into the
  trace record, and from there into the UI banner and the PDF watermark.
* The registry never falls back to this adapter silently. It is selected only when
  ``USE_MOCK_CHAIN_DATA=true`` is set explicitly.
* Counterparties are derived from the same documented seed namespace as the demo labels, so
  paths terminate at the fictional demo VASPs rather than at anything real.

Scenarios are deliberate rather than random, because a demo needs a path that behaves the
same way every time:

* ``clean``  — subject → two intermediates → a demo exchange deposit address (3 hops).
* ``mixer``  — subject → a demo mixer → intermediate → a demo custody deposit, so the risk
  engine has something to fire on.
* ``dead_end`` — subject → intermediates that never reach a labelled address, exercising the
  "No reliable VASP attribution found" path.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from app.blockchain.addresses import AddressValidation, canonicalize, validate_address
from app.blockchain.base import NormalizedTx, Page
from app.database.seeds.demo_fixtures import SEED_NAMESPACE, derive_address
from app.schemas.common import Chain, DataProvenance, Direction, TxKind, TxStatus

#: Fixed epoch for every mock timestamp, so a trace is byte-identical across runs.
MOCK_EPOCH = datetime(2026, 8, 1, 9, 0, 0, tzinfo=UTC)

NATIVE = {Chain.ETHEREUM: ("ETH", 18), Chain.TRON: ("TRX", 6)}
TOKEN = {Chain.ETHEREUM: ("USDT", 6), Chain.TRON: ("USDT", 6)}


def _seeded_int(*parts: str) -> int:
    digest = hashlib.sha256("|".join((SEED_NAMESPACE, "mock", *parts)).encode()).digest()
    return int.from_bytes(digest[:8], "big")


def _addr(chain: Chain, seed: str) -> str:
    """Derived address in **canonical** form.

    ``derive_address`` returns the display form (EIP-55 checksummed on Ethereum), but
    every lookup in this module and in the label matcher uses the canonical form. Mixing
    the two is the DPRD sec.17 format-mismatch failure: the adjacency map would be keyed
    by checksummed addresses while lookups arrive lowercased, and no hop would ever match.
    """
    return canonicalize(derive_address(chain.value, seed), chain)


def mock_subject(chain: Chain, scenario: str) -> str:
    """The demo subject wallet for a scenario. Published so the demo can paste it in."""
    return _addr(chain, f"mock/subject/{scenario}")


@dataclass(frozen=True, slots=True)
class _Hop:
    """One edge in a scripted scenario."""

    sender: str
    recipient: str
    amount: Decimal
    asset: str
    decimals: int
    minutes_after_epoch: int


class MockAdapter:
    """Implements :class:`app.blockchain.base.ChainAdapter` with synthetic data."""

    provenance = DataProvenance.MOCK_DEMO

    def __init__(self, chain: Chain) -> None:
        if chain not in NATIVE:
            raise ValueError(f"no mock data defined for {chain.value}")
        self.chain = chain
        self.native_asset = NATIVE[chain][0]
        self._edges = self._build_edges()

    # ─── scenario construction ──────────────────────────────────────────────

    def _build_edges(self) -> dict[str, list[_Hop]]:
        """Adjacency map for every scripted scenario, keyed by sender."""
        native, native_dp = NATIVE[self.chain]
        token, token_dp = TOKEN[self.chain]

        def addr(seed: str) -> str:
            return _addr(self.chain, seed)

        # Terminals are the demo fixture's own addresses, so a trace lands on a label that
        # actually exists in the database after `make seed-demo`.
        exchange_deposit = addr(
            "meridian/eth/deposit/1" if self.chain is Chain.ETHEREUM else "meridian/trx/deposit/1"
        )
        custody_deposit = addr(
            "kavach/eth/hot/1" if self.chain is Chain.ETHEREUM else "kavach/trx/deposit/1"
        )
        mixer = addr(
            "obscura/eth/router/1" if self.chain is Chain.ETHEREUM else "obscura/trx/router/1"
        )

        edges: dict[str, list[_Hop]] = {}

        def link(
            sender: str, recipient: str, amount: str, asset: str, dp: int, minute: int
        ) -> None:
            edges.setdefault(sender, []).append(
                _Hop(sender, recipient, Decimal(amount), asset, dp, minute)
            )

        # clean: subject -> i1 -> i2 -> exchange deposit
        clean = mock_subject(self.chain, "clean")
        c1, c2 = addr("mock/clean/i1"), addr("mock/clean/i2")
        link(clean, c1, "12.5", native, native_dp, 0)
        link(clean, addr("mock/clean/dust"), "0.004", native, native_dp, 5)
        link(c1, c2, "11.9", native, native_dp, 40)
        link(c2, exchange_deposit, "11.4", native, native_dp, 95)
        link(c2, addr("mock/clean/side"), "0.4", native, native_dp, 100)

        # mixer: subject -> mixer -> i1 -> custody deposit
        laundered = mock_subject(self.chain, "mixer")
        m1 = addr("mock/mixer/i1")
        link(laundered, mixer, "40000", token, token_dp, 0)
        link(mixer, m1, "19800", token, token_dp, 180)
        link(m1, custody_deposit, "19500", token, token_dp, 400)

        # dead_end: three hops of unlabelled addresses, no VASP anywhere
        dead = mock_subject(self.chain, "dead_end")
        d1, d2 = addr("mock/dead/i1"), addr("mock/dead/i2")
        link(dead, d1, "3.2", native, native_dp, 0)
        link(d1, d2, "3.1", native, native_dp, 60)
        link(d2, addr("mock/dead/i3"), "3.0", native, native_dp, 120)

        return edges

    def _derived_edges(self, sender: str) -> list[_Hop]:
        """Fallback for an address outside any scenario.

        Returns two deterministic counterparties so an arbitrary pasted address still
        produces a graph. Traversal is depth-capped, so this cannot run away.
        """
        native, decimals = NATIVE[self.chain]
        seed = _seeded_int(self.chain.value, sender)
        return [
            _Hop(
                sender=sender,
                recipient=_addr(self.chain, f"mock/derived/{sender}/{index}"),
                # Whole units derived from the seed; deterministic, and never zero.
                amount=Decimal(1 + (seed >> (index * 8)) % 50) / Decimal(10),
                asset=native,
                decimals=decimals,
                minutes_after_epoch=30 * (index + 1),
            )
            for index in range(2)
        ]

    # ─── contract ───────────────────────────────────────────────────────────

    def validate_address(self, address: str) -> AddressValidation:
        return validate_address(address, self.chain)

    def _hops(self, address: str, direction: Direction) -> list[_Hop]:
        canonical = self.validate_address(address).canonical_address
        if canonical is None:
            return []
        if direction is Direction.IN:
            return [
                hop for hops in self._edges.values() for hop in hops if hop.recipient == canonical
            ]
        return self._edges.get(canonical) or self._derived_edges(canonical)

    def _to_tx(self, hop: _Hop) -> NormalizedTx:
        raw = int(hop.amount * (Decimal(10) ** hop.decimals))
        digest = hashlib.sha256(
            f"{hop.sender}|{hop.recipient}|{hop.amount}|{hop.asset}".encode()
        ).hexdigest()
        return NormalizedTx(
            chain=self.chain,
            tx_hash=f"0x{digest[:64]}",
            block_timestamp=MOCK_EPOCH + timedelta(minutes=hop.minutes_after_epoch),
            from_address=hop.sender,
            to_address=hop.recipient,
            asset_symbol=hop.asset,
            amount=hop.amount,
            amount_raw=str(raw),
            decimals=hop.decimals,
            kind=TxKind.NATIVE if hop.asset == self.native_asset else TxKind.TOKEN,
            status=TxStatus.SUCCESS,
            provenance=DataProvenance.MOCK_DEMO,  # never anything else
        )

    def _page(self, hops: list[_Hop], limit: int) -> Page:
        transactions = tuple(
            sorted(
                (self._to_tx(hop) for hop in hops[:limit]),
                key=lambda tx: tx.block_timestamp,
                reverse=True,
            )
        )
        return Page(
            transactions=transactions,
            next_cursor=None,
            complete=True,
            provenance=DataProvenance.MOCK_DEMO,
            api_calls=0,
        )

    async def get_wallet_transactions(
        self,
        address: str,
        *,
        direction: Direction = Direction.OUT,
        limit: int = 200,
        cursor: str | None = None,
        force_refresh: bool = False,
    ) -> Page:
        hops = [h for h in self._hops(address, direction) if h.asset == self.native_asset]
        return self._page(hops, limit)

    async def get_token_transfers(
        self,
        address: str,
        *,
        direction: Direction = Direction.OUT,
        limit: int = 200,
        cursor: str | None = None,
        force_refresh: bool = False,
    ) -> Page:
        hops = [h for h in self._hops(address, direction) if h.asset != self.native_asset]
        return self._page(hops, limit)

    async def get_transaction(self, tx_hash: str) -> NormalizedTx | None:
        wanted = tx_hash.strip().lower()
        for hops in self._edges.values():
            for hop in hops:
                tx = self._to_tx(hop)
                if tx.tx_hash == wanted:
                    return tx
        return None

    def normalize_transaction(self, raw: dict[str, Any]) -> NormalizedTx | None:
        """Present for contract completeness; mock data is generated, never parsed."""
        return None


#: Subject wallets the demo can use, per chain. Printed by the offline-mode banner.
def demo_subjects(chain: Chain) -> dict[str, str]:
    return {scenario: mock_subject(chain, scenario) for scenario in ("clean", "mixer", "dead_end")}
