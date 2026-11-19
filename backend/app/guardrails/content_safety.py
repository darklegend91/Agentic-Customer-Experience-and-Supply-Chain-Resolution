"""Bounded heuristic screening; scoped tools and approval remain mandatory."""

from __future__ import annotations

import base64
import binascii
import html
import math
import re
import unicodedata
from dataclasses import dataclass
from typing import Any
from urllib.parse import unquote

_PATTERNS = {
    "instruction_override": (
        r"\b(?:skip|bypass|disable|ignore)\b.{0,50}\b(?:human|reviewer|approval|authorization)\b",
        r"\b(?:proceed|issue|process|execute|refund|approve)\b.{0,50}\bwithout\b.{0,30}\b(?:human|reviewer|approval|authorization)\b",
        r"\b(?:ignore|disregard|discard|forget|override|bypass|break)\b.{0,160}\b"
        r"(?:previous|prior|all|system|developer|safety|security|the)\b.{0,80}\b"
        r"(?:instruction|policy|rule|prompt|restriction|guardrail)s?\b",
        r"\b(?:reveal|print|show|dump|repeat|expose|send|upload|transmit)\b.{0,100}\b"
        r"(?:system prompt|developer message|secret|credential|private data|another customer|"
        r"api[ _-]?key|access[ _-]?token|password|bearer token)s?\b",
        r"\b(?:pretend|act as|roleplay as)\b.{0,80}\b(?:admin|administrator|supervisor|system)\b",
        r"\b(?:jailbreak|prompt injection)\b",
    ),
    "role_spoofing": (
        r"<\s*/?\s*(?:system|developer|assistant|tool)(?:\s[^>]{0,100})?>",
        r"\[(?:/?INST|SYSTEM)\]|<<\s*/?SYS\s*>>|<\|(?:im_start|im_end|system|assistant|eot_id|start_header_id)\|>",
        r'''["']role["']\s*:\s*["'](?:system|developer|assistant|tool)["']''',
        r"(?:^|\n)\s*(?:system|developer)\s*:",
    ),
    "executable_payload": (
        r"\b(?:pip3?|uv\s+pip|npm|pnpm|yarn)\s+(?:install|add)\b",
        r"\b(?:curl|wget)\b[^\n]{0,300}\|\s*(?:ba)?sh\b",
        r"\b(?:os\.system|subprocess\.(?:run|Popen|call)|__import__)\s*\(",
        r"\$\([^\n]{1,300}\)|`(?:curl|wget|bash|sh|cat|python)[^`]{1,300}`",
        r"['\";]\s*;?\s*(?:drop\s+table|truncate\s+table|union\s+select)\b",
        r"\b(?:or|and)\s+['\"]?1['\"]?\s*=\s*['\"]?1['\"]?\s*(?:--|#)",
    ),
    "active_content": (
        r"<\s*(?:script|iframe|object|embed|img|svg|math|link|style)\b",
        r"\b(?:javascript|vbscript)\s*:|data\s*:\s*text/html",
        r"!\[[^\]]{0,200}\]\s*\(",
        r"\bon(?:error|load|click)\s*=",
        r"(?:^|\n)\s*\[[^\]]{1,200}\]\s*:\s*\S",
        r"<\s*(?:https?|ftp|file)://|(?<!:)//[A-Za-z0-9.-]+(?:/|\b)",
    ),
}
_RULES = {code: tuple(re.compile(p, re.IGNORECASE | re.DOTALL) for p in patterns)
          for code, patterns in _PATTERNS.items()}
_TOKEN = re.compile(r"(?<![\w/-])[A-Za-z0-9+/_=-]{24,}(?![\w/-])")
_ESCAPE = re.compile(r"\\u([0-9a-fA-F]{4})|\\x([0-9a-fA-F]{2})")
_HEX = re.compile(r"\b(?:hex\s*:\s*|0x)([0-9a-fA-F]{24,})\b")
_LOOKALIKES = str.maketrans("аеорсхуіјѕΑΒΕΖΗΙΚΜΝΟΡΤΥΧ", "aeopcxyijsABEZHIKMNOPTYX")


@dataclass(frozen=True)
class TextInspection:
    text: str
    risk_codes: tuple[str, ...]


class UnsafeContentError(ValueError):
    """Payload-free error suitable for HTTP/MCP callers."""


class _InspectionLimit(ValueError):
    pass


def _normalize(value: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKC", value)
                   if unicodedata.category(c) != "Cf")


def _variants(value: str):
    """Decode only bounded text variants; never evaluate code or fetch URLs."""
    pending, seen = [(value, 0)], set()
    while pending and len(seen) < 16:
        current, depth = pending.pop(0)
        if current in seen:
            continue
        seen.add(current)
        yield current
        candidates = [unquote(current), html.unescape(current),
                      _ESCAPE.sub(lambda m: chr(int(m[1] or m[2], 16)), current)]
        hex_matches, tokens = list(_HEX.finditer(current)), list(_TOKEN.finditer(current))
        if len(hex_matches) > 8 or len(tokens) > 8:
            raise _InspectionLimit
        for match in hex_matches:
            try:
                candidates.append(bytes.fromhex(match[1]).decode("utf-8"))
            except (ValueError, UnicodeError):
                pass
        for match in tokens:
            token = match[0]
            try:
                candidates.append(base64.b64decode(token + "=" * (-len(token) % 4),
                                  altchars=b"-_", validate=True).decode("utf-8"))
            except (binascii.Error, UnicodeError, ValueError):
                pass
        for candidate in candidates:
            candidate = _normalize(candidate)
            if candidate != current and candidate not in seen:
                if depth >= 3 or len(candidate) > 20000:
                    raise _InspectionLimit
                pending.append((candidate, depth + 1))
    if any(candidate not in seen for candidate, _ in pending):
        raise _InspectionLimit


def inspect_text(value: str, *, max_chars: int = 5000) -> TextInspection:
    if not isinstance(value, str):
        return TextInspection("", ("invalid_text",))
    if len(value) > max_chars:
        return TextInspection("", ("text_too_long",))
    if any(unicodedata.category(c) in {"Cc", "Cs"} and c not in "\n\r\t" for c in value):
        return TextInspection("", ("prohibited_control_character",))
    normalized = _normalize(value).replace("\r\n", "\n").replace("\r", "\n").strip()
    if len(normalized) > max_chars:
        return TextInspection("", ("text_too_long",))
    risks = set()
    from ..security.pii_masking import mask_sensitive_text
    try:
        for variant in _variants(normalized):
            if variant != normalized and mask_sensitive_text(variant) != variant:
                risks.add("encoded_sensitive_content")
            if any(unicodedata.category(c) in {"Cc", "Cs"} and c not in "\n\r\t" for c in variant):
                risks.add("prohibited_control_character")
            for code, patterns in _RULES.items():
                if any(pattern.search(variant.translate(_LOOKALIKES)) for pattern in patterns):
                    risks.add(code)
    except _InspectionLimit:
        risks.add("encoding_inspection_limit")
    return TextInspection(normalized, tuple(sorted(risks)))


def require_safe_text(value: str, *, max_chars: int = 5000) -> str:
    result = inspect_text(value, max_chars=max_chars)
    if result.risk_codes or not result.text:
        raise UnsafeContentError("Untrusted content requires security review")
    return result.text


def evidence_risk_codes(value: Any) -> list[str]:
    """Screen bounded JSON-like tool results, including keys and nested notes."""
    from ..security.pii_masking import mask_sensitive_text

    pending, nodes, chars, risks = [(value, 0)], 0, 0, set()
    while pending:
        item, depth = pending.pop()
        nodes += 1
        if nodes > 4000 or depth > 16:
            return ["evidence_structure_limit"]
        if isinstance(item, str):
            chars += len(item)
            if chars > 120000:
                return ["evidence_text_limit"]
            risks.update(inspect_text(item, max_chars=16000).risk_codes)
            if mask_sensitive_text(item) != item:
                risks.add("sensitive_evidence")
        elif isinstance(item, dict):
            if len(item) > 4000:
                return ["evidence_structure_limit"]
            for key, child in item.items():
                if not isinstance(key, str):
                    risks.add("invalid_evidence_type")
                else:
                    pending.append((key, depth + 1))
                pending.append((child, depth + 1))
        elif isinstance(item, (list, tuple)):
            if len(item) > 4000:
                return ["evidence_structure_limit"]
            pending.extend((child, depth + 1) for child in item)
        elif item is not None and not isinstance(item, (bool, int, float)):
            risks.add("invalid_evidence_type")
        elif isinstance(item, float) and not math.isfinite(item):
            risks.add("invalid_evidence_number")
    return sorted(risks)


def require_safe_evidence(value: Any) -> None:
    if evidence_risk_codes(value):
        raise UnsafeContentError("Retrieved evidence requires security review")
