"""Compatibility entry point for the shared deterministic content guard."""

from .content_safety import inspect_text


def contains_instruction_override(text: str) -> bool:
    """Flag suspicious text; scoped tools remain the security boundary."""
    return bool(inspect_text(text).risk_codes)
