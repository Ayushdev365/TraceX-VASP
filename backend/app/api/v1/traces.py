"""Trace investigation endpoints."""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import Response

from app.blockchain.mock import demo_subjects
from app.core.errors import ResourceNotFound, ReviewRequired
from app.deps import DbSession, RequireApiKey
from app.reports.json_report import build_json_report
from app.reports.pdf_report import build_pdf_report
from app.sahyog.mock_disclosure import build_mock_disclosure
from app.schemas.common import Chain
from app.schemas.trace import (
    DemoSubjectsResponse,
    DisclosureDraftResponse,
    TraceReportResponse,
    TraceRequest,
    TraceResultResponse,
    TraceReviewRequest,
    TraceReviewResponse,
)
from app.services.trace_service import run_trace_investigation
from app.services.trace_store import get_review, get_trace_result, save_review

router = APIRouter(tags=["traces"], dependencies=[RequireApiKey])


@router.get(
    "/traces/demo-subjects",
    response_model=DemoSubjectsResponse,
    summary="List deterministic mock wallets for offline demos",
)
async def list_demo_subjects() -> DemoSubjectsResponse:
    return DemoSubjectsResponse(
        subjects={
            Chain.ETHEREUM: demo_subjects(Chain.ETHEREUM),
            Chain.TRON: demo_subjects(Chain.TRON),
        }
    )


@router.post("/traces", response_model=TraceResultResponse, summary="Run a trace investigation")
async def create_trace(request: TraceRequest, session: DbSession) -> TraceResultResponse:
    return await run_trace_investigation(session, request)


@router.get(
    "/traces/{trace_id}",
    response_model=TraceResultResponse,
    summary="Fetch a completed trace investigation result",
)
async def get_trace(trace_id: str) -> TraceResultResponse:
    result = get_trace_result(trace_id)
    if result is None:
        raise ResourceNotFound("Trace result not found.", details={"trace_id": trace_id})
    return result


@router.post(
    "/traces/{trace_id}/review",
    response_model=TraceReviewResponse,
    summary="Record investigator review decision",
)
async def review_trace(trace_id: str, request: TraceReviewRequest) -> TraceReviewResponse:
    if get_trace_result(trace_id) is None:
        raise ResourceNotFound("Trace result not found.", details={"trace_id": trace_id})
    save_review(trace_id, request.decision, request.note)
    return TraceReviewResponse(trace_id=trace_id, decision=request.decision, note=request.note)


@router.get(
    "/traces/{trace_id}/report.json",
    response_model=TraceReportResponse,
    summary="Render a JSON investigation report",
)
async def get_trace_report(trace_id: str) -> TraceReportResponse:
    result = get_trace_result(trace_id)
    if result is None:
        raise ResourceNotFound("Trace result not found.", details={"trace_id": trace_id})
    return build_json_report(result)


@router.get("/traces/{trace_id}/report.pdf", summary="Render a PDF investigation report")
async def get_trace_pdf_report(trace_id: str) -> Response:
    result = get_trace_result(trace_id)
    if result is None:
        raise ResourceNotFound("Trace result not found.", details={"trace_id": trace_id})
    return Response(
        content=build_pdf_report(result),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="vasptrace-{trace_id}.pdf"'},
    )


@router.post(
    "/traces/{trace_id}/disclosure",
    response_model=DisclosureDraftResponse,
    summary="Draft a mock SAHYOG disclosure payload",
)
async def create_disclosure(trace_id: str) -> DisclosureDraftResponse:
    result = get_trace_result(trace_id)
    if result is None:
        raise ResourceNotFound("Trace result not found.", details={"trace_id": trace_id})
    review = get_review(trace_id)
    if review is None or review[0].value != "accepted":
        raise ReviewRequired()
    return build_mock_disclosure(result)
