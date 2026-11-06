"""Consistent, value-redacted HTTP error envelopes."""

from __future__ import annotations

import json
import logging

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from ..observability.logging import log_safe_error


logger = logging.getLogger("agentic_customer_support.errors")


def _request_id(request: Request) -> str:
    return getattr(request.state, "request_id", "unavailable")


def _error(request: Request, status_code: int, code: str, message: str, fields: list[str] | None = None):
    return JSONResponse(
        status_code=status_code,
        content={
            "request_id": _request_id(request),
            "error": {
                "code": code,
                "message": message,
                "fields": fields or [],
            },
        },
        headers={"X-Request-ID": _request_id(request)},
    )


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError):
        fields = sorted({
            ".".join(str(part) for part in error.get("loc", ()) if part not in {"body", "query", "path"})
            for error in exc.errors()
        } - {""})
        return _error(request, 422, "validation_error", "Request validation failed.", fields)

    @app.exception_handler(HTTPException)
    async def http_error(request: Request, exc: HTTPException):
        status = exc.status_code
        codes = {
            400: ("bad_request", "The request could not be processed."),
            401: ("unauthorized", "Authentication is required."),
            403: ("forbidden", "The request is not permitted."),
            404: ("not_found", "The requested resource was not found."),
            409: ("conflict", "The request conflicts with the current record state."),
            422: ("invalid_request", "The request is invalid."),
            429: ("rate_limited", "Too many requests."),
            503: ("service_unavailable", "A required service is unavailable."),
        }
        code, message = codes.get(status, ("request_failed", "The request could not be completed."))
        if status < 500 and isinstance(exc.detail, str) and len(exc.detail) <= 160:
            message = exc.detail
        return _error(request, status, code, message)

    @app.exception_handler(Exception)
    async def unexpected_error(request: Request, exc: Exception):
        log_safe_error(
            logger,
            event="http_request_failed",
            request_id=_request_id(request),
            stage=getattr(request.scope.get("route"), "path", "unmatched"),
            error_type=type(exc).__name__,
        )
        return _error(request, 500, "internal_error", "An internal error occurred.")
