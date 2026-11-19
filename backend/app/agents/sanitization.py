"""Deterministic sanitization agent with no model, network or tool access."""

from __future__ import annotations

from typing import Any

from ..guardrails.content_safety import inspect_text
from ..security.pii_masking import mask_sensitive_text


def sanitize_request(state: dict[str, Any]) -> dict[str, Any]:
    risks = {"previous_input_rejected"} if state.get("input_error_code") == "unsafe_input" else set()
    cleaned = {}
    for field, limit in (("message", 5000), ("query", 3000)):
        value = state.get(field)
        if value is None or value == "":
            cleaned[field] = value
            continue
        result = inspect_text(value, max_chars=limit)
        risks.update(result.risk_codes)
        if not result.text:
            risks.add("empty_normalized_text")
        cleaned[field] = mask_sensitive_text(result.text)
    report = {"version": "sanitization-v1", "verdict": "blocked" if risks else "passed",
              "risk_codes": sorted(risks)}
    if risks:
        return {"message": "", "query": None, "sanitization": report,
                "input_error_code": "unsafe_input", "error_code": "unsafe_input",
                "status": "escalated", "specialist": "manual_review", "triage_ready": False,
                "reason_codes": ["unsafe_input", *sorted(risks)]}
    return {**cleaned, "sanitization": report}
