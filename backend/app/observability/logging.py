"""PII-safe structured logging helpers for API request diagnostics."""

from __future__ import annotations

import json
import logging
from typing import Any


def log_request_complete(
    logger: logging.Logger,
    *,
    request_id: str,
    method: str,
    route: str,
    status_code: int,
    latency_ms: float,
    error_type: str | None = None,
    error_category: str | None = None,
) -> None:
    """Log only a safe route template and operational metadata, never request data."""
    event: dict[str, Any] = {
        "event": "http_request_complete",
        "request_id": request_id,
        "method": method,
        "route": route,
        "status_code": status_code,
        "latency_ms": round(latency_ms, 2),
    }
    if error_type:
        event["error_type"] = error_type
    if error_category:
        event["error_category"] = error_category
    logger.info(json.dumps(event, separators=(",", ":"), sort_keys=True))


def log_safe_error(
    logger: logging.Logger,
    *,
    event: str,
    request_id: str,
    stage: str,
    error_type: str,
) -> None:
    """Log an error category without exception text, query data, or customer content."""
    logger.error(json.dumps({
        "event": event,
        "request_id": request_id,
        "stage": stage,
        "error_type": error_type,
    }, separators=(",", ":"), sort_keys=True))
