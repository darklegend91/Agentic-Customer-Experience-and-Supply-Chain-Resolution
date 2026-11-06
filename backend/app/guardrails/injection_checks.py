"""Conservative keyword screening for obvious instruction-override attempts.

This is only an early triage signal. Tool isolation, allowlisted routing, scoped
read access, and human review remain the actual security boundaries.
"""

from __future__ import annotations

import re


_OVERRIDE_PATTERNS = (
    re.compile(
        r"\b(?:without|skip|bypass|disable|ignore)\b.{0,50}\b(?:human|reviewer|approval|authorization)\b",
        flags=re.IGNORECASE | re.DOTALL,
    ),
    re.compile(
        r"\b(?:reveal|print|show|dump|expose|send)\b.{0,100}\b(?:api[ _-]?key|access[ _-]?token|password|bearer token)s?\b",
        flags=re.IGNORECASE | re.DOTALL,
    ),
    re.compile(
        r"\b(ignore|disregard|forget|override|bypass|break)\b.{0,160}\b"
        r"(previous|prior|all|system|developer|safety|security|the)\b.{0,80}\b"
        r"(instruction|policy|rule|prompt|restriction|guardrail)s?\b",
        flags=re.IGNORECASE | re.DOTALL,
    ),
    re.compile(
        r"\b(reveal|print|show|dump|repeat|expose)\b.{0,100}\b"
        r"(system prompt|developer message|secret|credential|private data|another customer)\b",
        flags=re.IGNORECASE | re.DOTALL,
    ),
    re.compile(
        r"\b(pretend|act as|roleplay as)\b.{0,80}\b(admin|administrator|supervisor|system)\b",
        flags=re.IGNORECASE | re.DOTALL,
    ),
    re.compile(r"\b(jailbreak|prompt injection|ignore all previous instructions)\b", flags=re.IGNORECASE),
)


def contains_instruction_override(text: str) -> bool:
    """Flag common explicit attempts; this check cannot detect all prompt attacks."""
    value = text or ""
    return any(pattern.search(value) for pattern in _OVERRIDE_PATTERNS)
