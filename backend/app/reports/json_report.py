"""JSON report rendering from stored trace results."""

from __future__ import annotations

import hashlib

from app.config import LEAD_NOT_PROOF, RISK_DISCLAIMER, SCORE_DISCLAIMER
from app.schemas.trace import TraceReportResponse, TraceResultResponse


def build_json_report(trace: TraceResultResponse) -> TraceReportResponse:
    payload: dict[str, object] = {
        "trace_id": trace.trace_id,
        "legal_notice": LEAD_NOT_PROOF,
        "score_notice": SCORE_DISCLAIMER,
        "risk_notice": RISK_DISCLAIMER,
        "subject": {
            "queried_address": trace.queried_address,
            "canonical_address": trace.canonical_address,
            "chain": trace.chain.value,
        },
        "summary": {
            "status": trace.status,
            "data_provenance": trace.data_provenance.value,
            "evidence_summary": trace.evidence_summary,
            "provenance_note": trace.provenance_note,
            "truncated": trace.truncated,
            "truncation_reason": trace.truncation_reason,
        },
        "primary_attribution": (
            trace.primary_attribution.model_dump(mode="json")
            if trace.primary_attribution is not None
            else None
        ),
        "attributions": [item.model_dump(mode="json") for item in trace.attributions],
        "risk_indicators": [item.model_dump(mode="json") for item in trace.risk_indicators],
        "paths": trace.paths,
        "nodes": [item.model_dump(mode="json") for item in trace.nodes],
        "edges": [item.model_dump(mode="json") for item in trace.edges],
    }
    digest = hashlib.sha256(str(payload).encode()).hexdigest()
    return TraceReportResponse(
        report_ref=f"RPT-{trace.trace_id[:8]}",
        trace_id=trace.trace_id,
        content_sha256=digest,
        payload=payload,
    )
