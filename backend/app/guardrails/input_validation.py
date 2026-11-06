"""Canonicalize and validate untrusted ticket text before model/tool use."""

from __future__ import annotations

import unicodedata


MAX_TICKET_CHARS = 5000


def normalize_ticket_message(message: str) -> str:
    """Normalize Unicode and whitespace; reject empty, non-text, or oversized input."""
    if not isinstance(message, str):
        raise ValueError("Ticket message must be text")
    normalized = unicodedata.normalize("NFKC", message)
    # Remove invisible formatting controls and reject remaining C0/C1 controls,
    # while preserving ordinary tabs/newlines used in pasted support messages.
    visible = []
    for char in normalized:
        category = unicodedata.category(char)
        if category == "Cf":
            continue
        if category == "Cc" and char not in {"\n", "\r", "\t"}:
            raise ValueError("Ticket message contains a prohibited control character")
        visible.append(char)
    normalized = "".join(visible).replace("\r\n", "\n").replace("\r", "\n")
    normalized = "\n".join(" ".join(line.split()) for line in normalized.split("\n")).strip()
    if not normalized:
        raise ValueError("Ticket message must not be empty")
    if len(normalized) > MAX_TICKET_CHARS:
        raise ValueError("Ticket message exceeds the 5000 character limit")
    return normalized
