"""Read-only, order-scoped customer loyalty and prior-contact evidence."""

from __future__ import annotations

from typing import Any

from ..api.schemas.evidence import CustomerSupportContextResponse
from ..db.repositories import RecordNotFound, get_customer_support_context_readonly
from ..runtime import require_local_development


def get_customer_support_context(order_id: str) -> dict[str, Any]:
    require_local_development()
    result = get_customer_support_context_readonly(order_id)
    if result.get("status") == "not_found":
        raise RecordNotFound("Order was not found in the development fixture")
    return CustomerSupportContextResponse.model_validate(result).model_dump(mode="json")
