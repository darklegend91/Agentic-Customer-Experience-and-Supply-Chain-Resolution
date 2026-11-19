"""Session-local order and customer references; backend authorization remains authoritative."""

from __future__ import annotations

import re
from typing import Any

_ORDER_ID = re.compile(r"\bORD-ID-[A-Za-z0-9][A-Za-z0-9_-]{3,64}\b", re.IGNORECASE)
_CUSTOMER_ID = re.compile(r"(?<![\w-])CUS-[0-9A-F]{10}(?![\w-])", re.IGNORECASE)


def resolve_order_context(message: str, manual_order_id: str, previous_order_id: str | None) -> str | None:
    """Resolve active order ID from manual input, message extraction, or previous turn context."""
    if manual_order_id.strip():
        return manual_order_id.strip()
    references = sorted(set(_ORDER_ID.findall(message)))
    if references:
        return references[0] if len(references) == 1 else None
    return previous_order_id or None


def resolve_customer_context(message: str, manual_customer_id: str, previous_customer_id: str | None) -> str | None:
    """Resolve active customer ID from manual input, message extraction, or previous turn context."""
    if manual_customer_id.strip():
        return manual_customer_id.strip().upper()
    references = sorted({match.upper() for match in _CUSTOMER_ID.findall(message)})
    if references:
        return references[0] if len(references) == 1 else None
    return previous_customer_id or None


def resolve_conversation_context(
    message: str,
    *,
    manual_order_id: str = "",
    manual_customer_id: str = "",
    previous_order_id: str | None = None,
    previous_customer_id: str | None = None,
) -> dict[str, str | None]:
    """Unified helper returning the active operational context for the current turn."""
    order_id = resolve_order_context(message, manual_order_id, previous_order_id)
    customer_id = resolve_customer_context(message, manual_customer_id, previous_customer_id)
    return {
        "order_id": order_id,
        "customer_id": customer_id,
    }
