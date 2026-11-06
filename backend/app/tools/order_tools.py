"""Shared order investigation operations used by FastAPI and MCP."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from ..api.schemas.evidence import OrderInvestigationEvidence, OrderSummaryResponse
from ..db.repositories import RecordNotFound, get_order_investigation_readonly, get_order_summary_readonly
from ..runtime import require_local_development


def get_order_summary(order_id: str) -> dict[str, Any]:
    require_local_development()
    try:
        result = get_order_summary_readonly(order_id)
    except RecordNotFound:
        result = {
            "source_system": "Neon Postgres",
            "as_of": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
            "status": "not_found",
            "order_id": order_id,
            "order": None,
            "items": [],
            "evidence_refs": {"order": [], "items": []},
            "missing_fields": ["order"],
        }
    return OrderSummaryResponse.model_validate(result).model_dump(mode="json")


def get_order_investigation(order_id: str) -> dict[str, Any]:
    require_local_development()
    try:
        result = get_order_investigation_readonly(order_id)
    except RecordNotFound:
        result = {
            "source_system": "Neon Postgres",
            "as_of": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
            "status": "not_found",
            "order_id": order_id,
            "order": None,
            "items": [],
            "delivery_events": [],
            "returns_refunds": [],
            "evidence_refs": {"order": [], "items": [], "delivery_events": [], "returns_refunds": []},
            "missing_fields": ["order"],
            "eligibility_decided": False,
        }
    return OrderInvestigationEvidence.model_validate(result).model_dump(mode="json")
