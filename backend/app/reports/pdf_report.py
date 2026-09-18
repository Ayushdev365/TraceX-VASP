"""Minimal PDF report rendering for stored trace results."""

from __future__ import annotations

from io import BytesIO

from reportlab.lib.pagesizes import LETTER
from reportlab.pdfgen import canvas

from app.config import LEAD_NOT_PROOF, SCORE_DISCLAIMER
from app.schemas.trace import TraceResultResponse


def build_pdf_report(trace: TraceResultResponse) -> bytes:
    buffer = BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=LETTER)
    width, height = LETTER
    y = height - 72

    def line(text: str, *, step: int = 16) -> None:
        nonlocal y
        if y < 72:
            pdf.showPage()
            y = height - 72
        pdf.drawString(72, y, text[:110])
        y -= step

    pdf.setTitle(f"VASPTrace Report {trace.trace_id}")
    pdf.setFont("Helvetica-Bold", 16)
    line("VASPTrace Investigation Report", step=24)
    pdf.setFont("Helvetica", 10)
    line(LEAD_NOT_PROOF)
    line(SCORE_DISCLAIMER, step=24)
    line(f"Trace ID: {trace.trace_id}")
    line(f"Chain: {trace.chain.value}")
    line(f"Subject: {trace.canonical_address}")
    line(f"Provenance: {trace.data_provenance.value}")
    line(f"Summary: {trace.evidence_summary}", step=24)

    if trace.primary_attribution:
        item = trace.primary_attribution
        line(f"Primary VASP: {item.vasp_name}")
        line(f"Score: {item.score} ({item.score_band})")
        line(f"Why: {item.score_breakdown.why_summary}", step=24)
    else:
        line(f"No reliable attribution: {trace.no_attribution_reason}", step=24)

    line("Risk indicators:")
    if trace.risk_indicators:
        for indicator in trace.risk_indicators[:10]:
            line(f"- {indicator.kind}: {indicator.summary}")
    else:
        line("- None")

    line("Evidence transactions:", step=20)
    for edge in trace.edges[:25]:
        line(f"- hop {edge.hop_index}: {edge.tx_hash} {edge.amount} {edge.asset_symbol}")

    if trace.data_provenance.value != "live_api":
        pdf.setFont("Helvetica-Bold", 42)
        pdf.setFillGray(0.85)
        pdf.rotate(35)
        pdf.drawString(210, 20, "DEMO DATA")
    pdf.save()
    return buffer.getvalue()
