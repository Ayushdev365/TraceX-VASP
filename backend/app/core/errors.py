"""Uniform error envelope.

Every failure the API emits has the same shape (see ``docs/API_CONTRACT.md`` sec.5):

    {"error": {"code": ..., "message": ..., "details": {...}, "request_id": ...}}

Upstream provider bodies, connection strings and API keys must never reach the client, so
handlers here deliberately discard the original exception text for unexpected errors and
log it instead.
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.logging import get_logger

logger = get_logger(__name__)


class VaspTraceError(Exception):
    """Base class for errors that are safe to show to an investigator."""

    code = "INTERNAL_ERROR"
    http_status = status.HTTP_500_INTERNAL_SERVER_ERROR
    message = "An unexpected error occurred."

    def __init__(
        self,
        message: str | None = None,
        *,
        details: dict[str, Any] | None = None,
    ) -> None:
        self.message = message or self.message
        self.details = details or {}
        super().__init__(self.message)


class ChainNotSupported(VaspTraceError):
    code = "CHAIN_NOT_SUPPORTED"
    http_status = status.HTTP_400_BAD_REQUEST
    message = "This blockchain is not supported yet."


class InvalidAddress(VaspTraceError):
    code = "INVALID_ADDRESS"
    http_status = status.HTTP_422_UNPROCESSABLE_ENTITY
    message = "The wallet address is not valid for the selected blockchain."


class ResourceNotFound(VaspTraceError):
    code = "NOT_FOUND"
    http_status = status.HTTP_404_NOT_FOUND
    message = "The requested resource does not exist."


class ReviewRequired(VaspTraceError):
    """Human-in-the-loop gate (DPRD sec.24). Not a configurable option."""

    code = "REVIEW_REQUIRED"
    http_status = status.HTTP_409_CONFLICT
    message = "Investigator review and acceptance are required before this action."


class RateLimited(VaspTraceError):
    code = "RATE_LIMITED"
    http_status = status.HTTP_429_TOO_MANY_REQUESTS
    message = "Too many requests. Please retry shortly."


class UpstreamProviderError(VaspTraceError):
    code = "UPSTREAM_PROVIDER_ERROR"
    http_status = status.HTTP_502_BAD_GATEWAY
    message = "The blockchain data provider could not be reached."


class UpstreamRateLimited(VaspTraceError):
    code = "UPSTREAM_RATE_LIMITED"
    http_status = status.HTTP_503_SERVICE_UNAVAILABLE
    message = "The blockchain data provider's rate limit was reached. Please retry shortly."


class Unauthorized(VaspTraceError):
    code = "UNAUTHORIZED"
    http_status = status.HTTP_401_UNAUTHORIZED
    message = "A valid API key is required."


def error_payload(
    code: str,
    message: str,
    *,
    details: dict[str, Any] | None = None,
    request_id: str | None = None,
) -> dict[str, Any]:
    return {
        "error": {
            "code": code,
            "message": message,
            "details": details or {},
            "request_id": request_id,
        }
    }


def _request_id(request: Request) -> str | None:
    value = getattr(request.state, "request_id", None)
    return str(value) if value else None


def register_exception_handlers(app: FastAPI) -> None:
    """Attach the handlers that guarantee a uniform envelope on every path."""

    @app.exception_handler(VaspTraceError)
    async def _handle_known(request: Request, exc: VaspTraceError) -> JSONResponse:
        headers: dict[str, str] = {}
        retry_after = exc.details.get("retry_after_s")
        if retry_after is not None:
            headers["Retry-After"] = str(int(retry_after))
        logger.warning(
            "handled_error",
            extra={"error_code": exc.code, "path": request.url.path, "detail": exc.message},
        )
        return JSONResponse(
            status_code=exc.http_status,
            content=error_payload(
                exc.code, exc.message, details=exc.details, request_id=_request_id(request)
            ),
            headers=headers,
        )

    @app.exception_handler(RequestValidationError)
    async def _handle_validation(request: Request, exc: RequestValidationError) -> JSONResponse:
        # Pydantic's raw errors can echo submitted values; keep only field + reason.
        fields = [
            {
                "field": ".".join(str(part) for part in err.get("loc", ()) if part != "body"),
                "reason": err.get("msg", "invalid value"),
            }
            for err in exc.errors()
        ]
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content=error_payload(
                "VALIDATION_ERROR",
                "One or more request fields are invalid.",
                details={"fields": fields},
                request_id=_request_id(request),
            ),
        )

    @app.exception_handler(StarletteHTTPException)
    async def _handle_http(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = {
            status.HTTP_404_NOT_FOUND: "NOT_FOUND",
            status.HTTP_405_METHOD_NOT_ALLOWED: "METHOD_NOT_ALLOWED",
            status.HTTP_401_UNAUTHORIZED: "UNAUTHORIZED",
        }.get(exc.status_code, "HTTP_ERROR")
        detail = exc.detail if isinstance(exc.detail, str) else "Request could not be completed."
        return JSONResponse(
            status_code=exc.status_code,
            content=error_payload(code, detail, request_id=_request_id(request)),
            headers=getattr(exc, "headers", None) or {},
        )

    @app.exception_handler(Exception)
    async def _handle_unexpected(request: Request, exc: Exception) -> JSONResponse:
        # Log the real cause; return nothing that could carry a key or a DSN.
        logger.exception(
            "unhandled_error",
            extra={"path": request.url.path, "error_type": type(exc).__name__},
        )
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content=error_payload(
                "INTERNAL_ERROR",
                "An unexpected error occurred. The incident has been logged.",
                request_id=_request_id(request),
            ),
        )
