"""Mask direct contact and payment identifiers before workflow checkpointing."""

from __future__ import annotations

import re


_EMAIL = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)
_PHONE = re.compile(r"(?<!\d)(?:\+?91[\s-]?)?[6-9]\d{9}(?!\d)")
_CARD = re.compile(r"(?<!\d)(?:\d[ -]?){13,19}(?!\d)")


def mask_sensitive_text(text: str) -> str:
    value = _EMAIL.sub("[EMAIL REDACTED]", text or "")
    value = _PHONE.sub("[PHONE REDACTED]", value)
    value = _CARD.sub("[PAYMENT NUMBER REDACTED]", value)
    return value
