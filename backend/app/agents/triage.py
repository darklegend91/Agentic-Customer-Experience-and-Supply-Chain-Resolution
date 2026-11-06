"""Laya-backed ticket classification and identifier validation node."""

from __future__ import annotations

import os
from typing import Any

from ..guardrails.injection_checks import contains_instruction_override
from ..tools.ticket_tools import classify_ticket_message


def triage_ticket(state: dict[str, Any]) -> dict[str, Any]:
    message = str(state.get("message") or "").strip()
    if not message:
        return {
            "classification": None,
            "triage_ready": False,
            "triage_reason_codes": ["ticket_message_missing"],
            "order_id": state.get("order_id"),
        }

    classification = classify_ticket_message(message)
    reasons = list(classification.get("risk_flags") or [])
    extracted = classification.get("entities", {}).get("order_ids", [])
    explicit_order_id = state.get("order_id")
    if len(extracted) > 1:
        reasons.append("multiple_order_references")
    elif extracted and explicit_order_id and extracted[0] != explicit_order_id:
        reasons.append("order_reference_conflict")
    elif extracted and not explicit_order_id:
        explicit_order_id = extracted[0]

    if contains_instruction_override(message):
        reasons.append("possible_instruction_override")

    threshold = float(os.getenv("WORKFLOW_MIN_CONFIDENCE", "0.65"))
    confidence = float(classification.get("confidence") or 0.0)
    ready = (
        classification.get("triage_status") == "ready"
        and classification.get("needs_human_review") is False
        and classification.get("automatic_routing_enabled") is True
        and not classification.get("fallback_used")
        and confidence >= threshold
        and not any(code in reasons for code in (
            "possible_instruction_override", "multiple_order_references", "order_reference_conflict",
            "laya_unavailable_baseline_fallback", "low_classifier_confidence",
            "classifier_disagreement", "baseline_corroboration_unavailable",
        ))
    )
    if confidence < threshold:
        reasons.append("workflow_confidence_below_threshold")

    return {
        "classification": classification,
        "order_id": explicit_order_id,
        "triage_ready": ready,
        "triage_reason_codes": sorted(set(reasons)),
    }
