"""Mask direct contact and payment identifiers before workflow checkpointing."""

from __future__ import annotations

import re
import unicodedata


_EMAIL = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)
_PHONE = re.compile(r"(?<!\d)(?:\+?91[\s-]?)?[6-9]\d{9}(?!\d)")
_CARD = re.compile(r"(?<!\d)(?:\d[ -]?){13,19}(?!\d)")
_CREDENTIAL = re.compile(
    r"\b(?:(?:[A-Z][A-Z0-9_]{0,63}_)?(?:TOKEN|SECRET|PASSWORD|API_KEY|SECRET_KEY|ACCESS_KEY_ID|DATABASE_URL)|"
    r"api[ _-]?key|access[ _-]?token|refresh[ _-]?token|password|passwd|secret|"
    r"authorization|database_url)[\"']?\s*[=:]\s*"
    r'''(?:"(?:\\.|[^"\\])*(?:"|$)|'(?:\\.|[^'\\])*(?:'|$)|[^\s"',;}{]+)''',
    re.IGNORECASE,
)
_BEARER = re.compile(r"\b(?:Bearer|Basic)\s+[A-Za-z0-9._~+/=-]{4,}", re.IGNORECASE)
_PROVIDER_KEY = re.compile(r"\b(?:sk-(?:proj-)?|gsk_|gh[pousr]_)[A-Za-z0-9_-]{12,}\b")
_CONNECTION = re.compile(r"\b(?:postgres(?:ql)?|mysql|redis|mongodb(?:\+srv)?)://[^\s\"'<>]+", re.IGNORECASE)
_PRIVATE_KEY = re.compile(r"-----BEGIN (?:[A-Z ]+ )?PRIVATE KEY-----.*?(?:-----END (?:[A-Z ]+ )?PRIVATE KEY-----|$)", re.DOTALL)


def mask_sensitive_text(text: str) -> str:
    original = text or ""
    canonical = "".join(c for c in unicodedata.normalize("NFKC", original) if unicodedata.category(c) != "Cf")
    value = _PRIVATE_KEY.sub("[SECRET REDACTED]", canonical)
    value = _CONNECTION.sub("[CONNECTION REDACTED]", value)
    value = _BEARER.sub("[SECRET REDACTED]", value)
    value = _CREDENTIAL.sub("[SECRET REDACTED]", value)
    value = _PROVIDER_KEY.sub("[SECRET REDACTED]", value)
    value = _EMAIL.sub("[EMAIL REDACTED]", value)
    value = _PHONE.sub("[PHONE REDACTED]", value)
    value = _CARD.sub("[PAYMENT NUMBER REDACTED]", value)
    return value if value != canonical else original
