"""End-to-end trace investigation orchestration."""

from __future__ import annotations

import hashlib
import uuid
from typing import cast

from sqlalchemy.ext.asyncio import AsyncSession

from app.attribution.scoring import score_candidates
from app.blockchain.addresses import validate_address
from app.blockchain.mock import MockAdapter
from app.blockchain.registry import IMPLEMENTED_CHAINS, get_adapter
from app.config import get_settings
from app.core.errors import ChainNotSupported, InvalidAddress
from app.graph.engine import Fetcher
from app.graph.types import TraversalResult
from app.risk.engine import detect_risk_indicators
from app.risk.types import RiskIndicator
from app.schemas.attribution import ScoredCandidate
from app.schemas.common import Chain, DataProvenance, TraceStatus
from app.schemas.trace import (
    TraceCandidateResult,
    TraceDataMode,
    TraceEdgeResult,
    TraceNodeResult,
    TraceRequest,
    TraceResultResponse,
    TraceRiskIndicatorResult,
)
from app.services.label_matcher import VaspLabelMatcher
from app.services.trace_store import save_trace_result


async def run_trace_investigation(
    session: AsyncSession,
    request: TraceRequest,
) -> TraceResultResponse:
    """Run the existing engines as one synchronous investigation pipeline."""
    if request.chain not in IMPLEMENTED_CHAINS:
        supported = sorted(chain.value for chain in IMPLEMENTED_CHAINS)
        raise ChainNotSupported(
            f"{request.chain.value} is not supported yet. "
            f"Currently available: {', '.join(supported)}.",
            details={"requested_chain": request.chain.value, "supported_chains": supported},
        )

    validation = validate_address(request.address, request.chain)
    if not validation.valid or validation.canonical_address is None:
        raise InvalidAddress(
            validation.error_message
            or "The wallet address is not valid for the selected blockchain.",
            details={
                "code": validation.error_code.value if validation.error_code else None,
                "suggested_chain": (
                    validation.suggested_chain.value if validation.suggested_chain else None
                ),
            },
        )

    adapter = _adapter_for_request(request.chain, request.data_mode, session)
    matcher = VaspLabelMatcher(session, adapter, request.chain)
    traversal = await matcher.run_traversal(
        validation.canonical_address,
        hop_depth=request.hop_depth,
        direction=request.direction,
    )
    risk_indicators = detect_risk_indicators(traversal)
    attributions = score_candidates(traversal, risk_indicators)

    result = _build_response(
        request=request,
        canonical_address=validation.canonical_address,
        traversal=traversal,
        risk_indicators=risk_indicators,
        attributions=attributions,
    )
    return save_trace_result(result)


def _adapter_for_request(
    chain: Chain,
    data_mode: TraceDataMode,
    session: AsyncSession,
) -> Fetcher:
    if data_mode is TraceDataMode.MOCK:
        return MockAdapter(chain)
    return cast(Fetcher, get_adapter(chain, session=session))


def _build_response(
    *,
    request: TraceRequest,
    canonical_address: str,
    traversal: TraversalResult,
    risk_indicators: list[RiskIndicator],
    attributions: list[ScoredCandidate],
) -> TraceResultResponse:
    primary = next((candidate for candidate in attributions if candidate.is_primary), None)
    trace_id = _trace_id(request, canonical_address, traversal, attributions, risk_indicators)
    return TraceResultResponse(
        trace_id=trace_id,
        status=TraceStatus.PARTIAL.value if traversal.truncated else TraceStatus.COMPLETED.value,
        queried_address=request.address,
        canonical_address=canonical_address,
        chain=request.chain,
        hop_depth=traversal.hop_depth,
        direction=traversal.direction,
        data_provenance=traversal.provenance,
        data_mode=request.data_mode,
        case_ref=request.case_ref,
        truncated=traversal.truncated,
        truncation_reason=traversal.truncation_reason,
        nodes_expanded=traversal.nodes_expanded,
        api_calls_made=traversal.api_calls,
        tx_analyzed_count=traversal.tx_analyzed,
        duration_ms=traversal.duration_ms,
        discovered_addresses=sorted(traversal.nodes),
        nodes=_nodes(traversal),
        edges=_edges(traversal),
        paths={address: list(path) for address, path in sorted(traversal.paths.items())},
        vasp_candidates=_candidates(traversal),
        attributions=attributions,
        primary_attribution=primary,
        no_attribution_reason=_no_attribution_reason(attributions, traversal),
        risk_indicators=_risk_indicators(risk_indicators),
        evidence_summary=_evidence_summary(traversal, attributions, risk_indicators),
        provenance_note=_provenance_note(traversal.provenance),
    )


def _nodes(traversal: TraversalResult) -> list[TraceNodeResult]:
    return [
        TraceNodeResult(
            address=node.address,
            role=node.role,
            hop_distance=node.hop_distance,
            expanded=node.expanded,
            not_expanded_reason=node.not_expanded_reason,
            matched_vasp_name=node.matched_vasp_name,
            matched_vasp_slug=node.matched_vasp_slug,
            matched_risk_entity_kind=node.matched_risk_entity_kind,
        )
        for node in sorted(
            traversal.nodes.values(),
            key=lambda item: (item.hop_distance, item.address),
        )
    ]


def _edges(traversal: TraversalResult) -> list[TraceEdgeResult]:
    return [
        TraceEdgeResult(
            from_address=edge.from_address,
            to_address=edge.to_address,
            tx_hash=edge.tx_hash,
            chain=edge.chain,
            direction=edge.direction,
            asset_symbol=edge.asset_symbol,
            amount=str(edge.amount),
            block_timestamp=edge.block_timestamp.isoformat(),
            hop_index=edge.hop_index,
        )
        for edge in sorted(traversal.edges, key=lambda item: (item.hop_index, item.tx_hash))
    ]


def _candidates(traversal: TraversalResult) -> list[TraceCandidateResult]:
    return [
        TraceCandidateResult(
            address=candidate.address,
            vasp_name=candidate.vasp_name,
            vasp_slug=candidate.vasp_slug,
            hop_distance=candidate.hop_distance,
            path=list(candidate.path),
        )
        for candidate in traversal.candidates
    ]


def _risk_indicators(indicators: list[RiskIndicator]) -> list[TraceRiskIndicatorResult]:
    return [
        TraceRiskIndicatorResult(
            kind=indicator.kind.value,
            severity=indicator.severity,
            detection_basis=indicator.detection_basis.value,
            summary=indicator.summary,
            evidence_addresses=list(indicator.evidence_addresses),
            evidence_tx_hashes=list(indicator.evidence_tx_hashes),
            penalty=indicator.penalty,
            details=indicator.details,
        )
        for indicator in indicators
    ]


def _no_attribution_reason(
    attributions: list[ScoredCandidate],
    traversal: TraversalResult,
) -> str | None:
    if any(candidate.is_primary for candidate in attributions):
        return None
    if traversal.truncated:
        return "trace_truncated_before_reliable_attribution"
    if not traversal.candidates:
        return "no_attributable_vasp_reached"
    return "score_below_threshold"


def _evidence_summary(
    traversal: TraversalResult,
    attributions: list[ScoredCandidate],
    risk_indicators: list[RiskIndicator],
) -> str:
    if attributions and attributions[0].is_primary:
        best = attributions[0]
        return (
            f"Found {len(traversal.nodes)} addresses and {len(traversal.edges)} transactions; "
            f"top VASP candidate is {best.vasp_name} with a {best.score_band} heuristic score."
        )
    return (
        f"Found {len(traversal.nodes)} addresses and {len(traversal.edges)} transactions; "
        f"no reliable VASP attribution was produced. Risk indicators: {len(risk_indicators)}."
    )


def _provenance_note(provenance: DataProvenance) -> str:
    if provenance is DataProvenance.MOCK_DEMO:
        return (
            "Synthetic mock-chain data was used; this result is for demo/offline validation only."
        )
    if provenance is DataProvenance.CACHED:
        return "Cached blockchain provider responses were used."
    if provenance is DataProvenance.MIXED:
        return "The result combines more than one data provenance source."
    return "Live blockchain provider data was used."


def _trace_id(
    request: TraceRequest,
    canonical_address: str,
    traversal: TraversalResult,
    attributions: list[ScoredCandidate],
    risk_indicators: list[RiskIndicator],
) -> str:
    digest = hashlib.sha256()
    digest.update(
        "|".join(
            (
                request.chain.value,
                canonical_address,
                str(traversal.hop_depth),
                traversal.direction.value,
                request.data_mode.value,
                str(traversal.truncated),
                get_settings().engine_version,
            )
        ).encode()
    )
    for edge in sorted(traversal.edges, key=lambda item: item.dedup_key):
        digest.update(edge.dedup_key.encode())
    for candidate in attributions:
        digest.update(f"{candidate.vasp_slug}:{candidate.score}:{candidate.rank}".encode())
    for indicator in risk_indicators:
        digest.update(f"{indicator.kind.value}:{indicator.evidence_addresses}".encode())
    return str(uuid.uuid5(uuid.NAMESPACE_URL, digest.hexdigest()))
