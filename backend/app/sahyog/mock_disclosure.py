"""Mock SAHYOG disclosure draft generation."""

from __future__ import annotations

from app.config import LEAD_NOT_PROOF, MOCK_SAHYOG_BANNER, RISK_DISCLAIMER, SCORE_DISCLAIMER
from app.schemas.trace import DisclosureDraftResponse, TraceResultResponse


def build_mock_disclosure(trace: TraceResultResponse) -> DisclosureDraftResponse:
    payload: dict[str, object] = {
        "trace_id": trace.trace_id,
        "chain": trace.chain.value,
        "subject_address": trace.canonical_address,
        "case_ref": trace.case_ref,
        "data_provenance": trace.data_provenance.value,
        "primary_vasp": (
            trace.primary_attribution.model_dump(mode="json")
            if trace.primary_attribution is not None
            else None
        ),
        "risk_indicators": [item.model_dump(mode="json") for item in trace.risk_indicators],
        "evidence_tx_hashes": [edge.tx_hash for edge in trace.edges],
        "notices": [LEAD_NOT_PROOF, SCORE_DISCLAIMER, RISK_DISCLAIMER],
    }
    return DisclosureDraftResponse(
        disclosure_ref=f"MOCK-SAHYOG-{trace.trace_id[:8]}",
        trace_id=trace.trace_id,
        banner=MOCK_SAHYOG_BANNER,
        payload=payload,
    )
