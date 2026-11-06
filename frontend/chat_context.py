"""Session-local order references; backend authorization remains authoritative."""

import re

_ORDER_ID = re.compile(r"\bORD-ID-[A-Za-z0-9][A-Za-z0-9_-]{3,64}\b", re.IGNORECASE)


def resolve_order_context(message: str, manual_order_id: str, previous_order_id: str | None) -> str | None:
    if manual_order_id.strip():
        return manual_order_id.strip()
    references = sorted(set(_ORDER_ID.findall(message)))
    if references:
        return references[0] if len(references) == 1 else None
    return previous_order_id or None
