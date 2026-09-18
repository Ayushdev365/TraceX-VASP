"""Adapter registry — the only place the reasoning layer resolves a chain.

Roadmap chains fail here with a clear, honest message rather than being quietly substituted
with something else. A chain is only offered once its adapter passes the DPRD sec.11 tracing
gate.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.blockchain.base import ChainAdapter
from app.blockchain.ethereum import EthereumAdapter
from app.core.errors import ChainNotSupported, VaspTraceError
from app.schemas.common import MVP_CHAINS, Chain

#: Chains with a working adapter in this build. Tron joins in Phase 4.
IMPLEMENTED_CHAINS: frozenset[Chain] = frozenset({Chain.ETHEREUM})

#: Chains on the roadmap, with the phase that will deliver them (DPRD sec.11).
ROADMAP_NOTES: dict[Chain, str] = {
    Chain.TRON: "Tron support lands next; its adapter is in progress.",
    Chain.BITCOIN: "Bitcoin is a Pilot-phase roadmap chain.",
    Chain.BNB: "BNB Chain is a Pilot-phase roadmap chain.",
    Chain.SOLANA: "Solana is a Scale-phase roadmap chain.",
    Chain.POLYGON: "Polygon is a Scale-phase roadmap chain.",
}


class ProviderNotConfigured(VaspTraceError):
    """The adapter exists but has no credentials, so it cannot read the chain.

    Reported as its own condition rather than as a generic failure: "no API key" and "the
    provider is down" need different fixes, and conflating them wastes demo-day minutes.
    """

    code = "PROVIDER_NOT_CONFIGURED"
    http_status = 503
    message = "No data provider is configured for this blockchain."


def get_adapter(chain: Chain, *, session: AsyncSession | None = None) -> ChainAdapter:
    """Return the adapter for ``chain``.

    Raises :class:`ChainNotSupported` for a roadmap chain and
    :class:`ProviderNotConfigured` when the adapter has no API key.
    """
    if chain not in IMPLEMENTED_CHAINS:
        note = ROADMAP_NOTES.get(chain, "This blockchain is not supported yet.")
        supported = ", ".join(sorted(c.value for c in IMPLEMENTED_CHAINS))
        raise ChainNotSupported(
            f"{chain.value} is not supported yet. {note} Currently available: {supported}.",
            details={
                "requested_chain": chain.value,
                "supported_chains": sorted(c.value for c in IMPLEMENTED_CHAINS),
                "mvp_target_chains": sorted(c.value for c in MVP_CHAINS),
            },
        )

    if chain is Chain.ETHEREUM:
        adapter = EthereumAdapter(session=session)
        if not adapter._api_key:
            raise ProviderNotConfigured(
                "Ethereum tracing needs ETHERSCAN_API_KEY. Set it in the backend's .env; "
                "no live blockchain data can be retrieved without it.",
                details={"chain": chain.value, "required_setting": "ETHERSCAN_API_KEY"},
            )
        return adapter

    raise ChainNotSupported(details={"requested_chain": chain.value})  # pragma: no cover


def is_chain_ready(chain: Chain) -> bool:
    """True when ``chain`` has both an adapter and the credentials to use it."""
    try:
        get_adapter(chain)
    except VaspTraceError:
        return False
    return True
