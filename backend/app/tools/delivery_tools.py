"""Shared delivery and return/refund read tools used by FastAPI and MCP."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from ..api.schemas.evidence import DeliveryEventsResponse, ReturnRefundResponse
from ..db.repositories import RecordNotFound, get_return_refund_status_readonly, list_delivery_events_readonly
from ..runtime import require_local_development


def list_delivery_events(order_id: str, *, limit: int = 100) -> dict[str, Any]:
    require_local_development()
    if not 1 <= limit <= 100:
        raise ValueError("limit must be between 1 and 100")
    try:
        result = list_delivery_events_readonly(order_id, limit=limit)
    except RecordNotFound:
        result = {
            "source_system": "Neon Postgres",
            "as_of": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
            "status": "not_found",
            "order_id": order_id,
            "events": [],
            "evidence_refs": [],
            "missing_fields": ["order"],
        }
    return DeliveryEventsResponse.model_validate(result).model_dump(mode="json")


def get_return_refund_status(order_id: str, *, limit: int = 50) -> dict[str, Any]:
    require_local_development()
    if not 1 <= limit <= 50:
        raise ValueError("limit must be between 1 and 50")
    try:
        result = get_return_refund_status_readonly(order_id, limit=limit)
    except RecordNotFound:
        result = {
            "source_system": "Neon Postgres",
            "as_of": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
            "status": "not_found",
            "order_id": order_id,
            "returns_refunds": [],
            "evidence_refs": [],
            "eligibility_decided": False,
            "missing_fields": ["order"],
        }
    return ReturnRefundResponse.model_validate(result).model_dump(mode="json")
