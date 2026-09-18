"""Small in-process trace-result store for the synchronous MVP API."""

from __future__ import annotations

from app.schemas.common import ReviewDecision
from app.schemas.trace import TraceResultResponse

_TRACE_RESULTS: dict[str, TraceResultResponse] = {}
_REVIEWS: dict[str, tuple[ReviewDecision, str | None]] = {}


def save_trace_result(result: TraceResultResponse) -> TraceResultResponse:
    _TRACE_RESULTS[result.trace_id] = result
    return result


def get_trace_result(trace_id: str) -> TraceResultResponse | None:
    return _TRACE_RESULTS.get(trace_id)


def save_review(trace_id: str, decision: ReviewDecision, note: str | None) -> None:
    _REVIEWS[trace_id] = (decision, note)


def get_review(trace_id: str) -> tuple[ReviewDecision, str | None] | None:
    return _REVIEWS.get(trace_id)


def clear_trace_results() -> None:
    _TRACE_RESULTS.clear()
    _REVIEWS.clear()
