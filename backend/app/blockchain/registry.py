"""Adapter registry — the only place the reasoning layer resolves a chain.

Roadmap chains fail here with a clear, honest message rather than being quietly substituted
with something else. A chain is only offered once its adapter passes the DPRD sec.11 tracing
gate.

Mock data is never a fallback. When a provider key is missing, the caller gets
``ProviderNotConfigured`` naming the setting to fix; synthetic data is served only when
``USE_MOCK_CHAIN_DATA=true`` is set deliberately.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.blockchain.base import ChainAdapter
from app.blockchain.ethereum import EthereumAdapter
from app.blockchain.mock import MockAdapter
from app.blockchain.tron import TronAdapter
from app.config import get_settings
from app.core.errors import ChainNotSupported, VaspTraceError
from app.schemas.common import MVP_CHAINS, Chain, DataProvenance

#: Chains with a working adapter in this build — the DPRD sec.31 MVP target.
IMPLEMENTED_CHAINS: frozenset[Chain] = frozenset({Chain.ETHEREUM, Chain.TRON})

#: Setting that must be present for each chain's live adapter to function.
REQUIRED_SETTING: dict[Chain, str] = {
    Chain.ETHEREUM: "ETHERSCAN_API_KEY",
    Chain.TRON: "TRONGRID_API_KEY",
}

#: Chains on the roadmap, with the phase that will deliver them (DPRD sec.11).
ROADMAP_NOTES: dict[Chain, str] = {
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


def _live_adapter(chain: Chain, session: AsyncSession | None) -> ChainAdapter:
    if chain is Chain.ETHEREUM:
        return EthereumAdapter(session=session)
    if chain is Chain.TRON:
        return TronAdapter(session=session)
    raise ChainNotSupported(details={"requested_chain": chain.value})  # pragma: no cover


def _has_credentials(chain: Chain) -> bool:
    settings = get_settings()
    return bool(
        {
            Chain.ETHEREUM: settings.etherscan_api_key,
            Chain.TRON: settings.trongrid_api_key,
        }.get(chain)
    )


def get_adapter(chain: Chain, *, session: AsyncSession | None = None) -> ChainAdapter:
    """Return the adapter for ``chain``.

    Raises :class:`ChainNotSupported` for a roadmap chain and
    :class:`ProviderNotConfigured` when a live adapter has no API key.
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

    if get_settings().use_mock_chain_data:
        # Opt-in only. Everything this returns is labelled mock_demo.
        return MockAdapter(chain)

    if not _has_credentials(chain):
        setting = REQUIRED_SETTING[chain]
        raise ProviderNotConfigured(
            f"{chain.value.title()} tracing needs {setting}. Set it in the backend's .env, "
            f"or set USE_MOCK_CHAIN_DATA=true to work offline with clearly-labelled "
            f"synthetic data.",
            details={"chain": chain.value, "required_setting": setting},
        )

    return _live_adapter(chain, session)


def adapter_provenance(chain: Chain) -> DataProvenance | None:
    """What kind of data this chain would return right now, or ``None`` if unavailable.

    Used by ``/meta/chains`` so the UI can state honestly whether a trace would be live or
    synthetic before the investigator runs one.
    """
    if chain not in IMPLEMENTED_CHAINS:
        return None
    if get_settings().use_mock_chain_data:
        return DataProvenance.MOCK_DEMO
    return DataProvenance.LIVE_API if _has_credentials(chain) else None


def is_chain_ready(chain: Chain) -> bool:
    """True when ``chain`` can actually be traced right now."""
    try:
        get_adapter(chain)
    except VaspTraceError:
        return False
    return True
