"""Per-request correlation and safe latency logging middleware."""

from __future__ import annotations

import asyncio
import logging
import os
import time
from contextlib import nullcontext
from uuid import uuid4

from fastapi import Request
from fastapi.responses import JSONResponse, Response

from ..runtime import LocalDevelopmentOnly, require_local_development
from ..observability.logging import log_request_complete
from ..observability.tracing import trace_stage, update_trace_span


logger = logging.getLogger("agentic_customer_support.requests")


def _request_timeout_seconds() -> float:
    try:
        configured = float(os.getenv("API_REQUEST_TIMEOUT_SECONDS", "30"))
    except ValueError:
        configured = 30.0
    return min(max(configured, 1.0), 120.0)


def install_request_middleware(app) -> None:
    """Add request IDs, local-only production fail-closed checks, and safe logs."""

    @app.middleware("http")
    async def request_middleware(request: Request, call_next) -> Response:
        request_id = str(uuid4())
        request.state.request_id = request_id
        started = time.perf_counter()

        response = None
        error_type = None
        if request.url.path != "/health":
            try:
                require_local_development()
            except LocalDevelopmentOnly:
                error_type = "local_only_guard"
                response = JSONResponse(
                    status_code=503,
                    content={
                        "request_id": request_id,
                        "error": {
                            "code": "service_unavailable",
                            "message": "This service is disabled outside local development.",
                            "fields": [],
                        },
                    },
                )

        if response is None:
            try:
                # Health and status polling keep their existing latency logs,
                # without creating a cloud trace on every UI refresh.
                monitor = request.url.path != "/health" and not (
                    request.method == "GET" and request.url.path.startswith("/workflows/")
                )
                context = trace_stage("api.request", {"request_id": request_id, "method": request.method}) if monitor else nullcontext(None)
                with context as span:
                    async with asyncio.timeout(_request_timeout_seconds()):
                        response = await call_next(request)
                    update_trace_span(span, output={
                        "status_code": response.status_code,
                        "route": getattr(request.scope.get("route"), "path", "unmatched"),
                        "latency_ms": round((time.perf_counter() - started) * 1000, 2),
                    })
            except TimeoutError:
                error_type = "request_timeout"
                response = JSONResponse(
                    status_code=504,
                    content={
                        "request_id": request_id,
                        "error": {
                            "code": "request_timeout",
                            "message": "The request exceeded its time limit.",
                            "fields": [],
                        },
                    },
                )
            except Exception as exc:
                error_type = type(exc).__name__
                response = JSONResponse(
                    status_code=500,
                    content={
                        "request_id": request_id,
                        "error": {
                            "code": "internal_error",
                            "message": "An internal error occurred.",
                            "fields": [],
                        },
                    },
                )

        response.headers["X-Request-ID"] = request_id
        route = request.scope.get("route")
        route_template = getattr(route, "path", "unmatched")
        log_request_complete(
            logger,
            request_id=request_id,
            method=request.method,
            route=route_template,
            status_code=response.status_code,
            latency_ms=(time.perf_counter() - started) * 1000,
            error_type=error_type,
            error_category=(
                "server_error" if response.status_code >= 500
                else "client_error" if response.status_code >= 400
                else None
            ),
        )
        return response
