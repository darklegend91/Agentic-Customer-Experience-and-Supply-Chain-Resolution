"""Shared ticket read and Laya-backed classification operations."""

from __future__ import annotations

import re
import os
from typing import Any

from ..api.schemas.ticket import TicketClassification, TicketDetailsResponse
from ..classification.laya import LayaClassifierError, classify_with_laya
from ..db.repositories import RecordNotFound
from ..db.repositories import get_ticket_readonly
from ..intent_classifier import classify_ticket as run_intent_classifier
from ..guardrails.injection_checks import contains_instruction_override
from ..guardrails.input_validation import normalize_ticket_message
from ..runtime import require_local_development
from ..security.pii_masking import mask_sensitive_text


_ORDER_ID = re.compile(r"\bORD-ID-[A-Za-z0-9][A-Za-z0-9_-]{3,64}\b", flags=re.IGNORECASE)
_ITEM_ID = re.compile(r"\bITM-[A-Za-z0-9][A-Za-z0-9_-]{3,64}\b", flags=re.IGNORECASE)
_PRODUCT_ID = re.compile(r"\bSKU-[A-Za-z0-9][A-Za-z0-9_-]{3,64}\b", flags=re.IGNORECASE)
_RETURN_ID = re.compile(r"\bRTN-[A-Za-z0-9][A-Za-z0-9_-]{3,64}\b", flags=re.IGNORECASE)
_DEFAULT_REVIEW_THRESHOLD = 0.65


def get_ticket_details(ticket_id: str) -> dict[str, Any]:
    require_local_development()
    try:
        result = get_ticket_readonly(ticket_id)
        missing_fields = [] if str(result.get("message") or "").strip() else ["message"]
        result.update({
            "status": "insufficient_data" if missing_fields else "found",
            "workflow_status": "not_persisted",
            "missing_fields": missing_fields,
        })
    except RecordNotFound:
        result = {
            "status": "not_found",
            "ticket_id": ticket_id,
            "message": None,
            "order_id": None,
            "workflow_status": "not_persisted",
            "missing_fields": ["ticket"],
        }
    return TicketDetailsResponse.model_validate(result).model_dump(mode="json")


def classify_ticket_message(message: str) -> dict[str, Any]:
    """Classify with Laya and a lexical second opinion; route only by explicit policy."""
    require_local_development()
    normalized = normalize_ticket_message(message)
    entities = {
        "order_ids": sorted(set(_ORDER_ID.findall(normalized))),
        "item_ids": sorted(set(_ITEM_ID.findall(normalized))),
        "product_ids": sorted(set(_PRODUCT_ID.findall(normalized))),
        "return_ids": sorted(set(_RETURN_ID.findall(normalized))),
    }
    if any(len(values) > 10 for values in entities.values()):
        bounded_entities = {key: values[:10] for key, values in entities.items()}
        return TicketClassification.model_validate({
            "intent": "other_or_unsupported",
            "confidence": 0.0,
            "classifier_version": "entity-limit-guardrail-v1",
            "classifier_provider": "input_guardrail",
            "fallback_used": False,
            "triage_status": "security_review",
            "risk_flags": ["too_many_extracted_references", "model_not_called_for_input_guardrail"],
            "entities": bounded_entities,
            "review_threshold": _DEFAULT_REVIEW_THRESHOLD,
            "needs_human_review": True,
            "baseline_intent": None,
            "models_agree": None,
            "confidence_calibrated": False,
            "automatic_routing_enabled": False,
        }).model_dump(mode="json")
    instruction_override = contains_instruction_override(normalized)
    if instruction_override:
        return TicketClassification.model_validate({
            "intent": "other_or_unsupported",
            "confidence": 0.0,
            "classifier_version": "input-guardrail-v1",
            "classifier_provider": "input_guardrail",
            "fallback_used": False,
            "triage_status": "security_review",
            "risk_flags": ["possible_instruction_override", "model_not_called_for_security_signal"],
            "entities": entities,
            "review_threshold": _DEFAULT_REVIEW_THRESHOLD,
            "needs_human_review": True,
            "baseline_intent": None,
            "models_agree": None,
            "confidence_calibrated": False,
            "automatic_routing_enabled": False,
        }).model_dump(mode="json")

    safe_message = mask_sensitive_text(normalized)
    try:
        result = classify_with_laya(safe_message)
    except LayaClassifierError:
        baseline = run_intent_classifier(safe_message)
        result = {
            **baseline,
            "provider": "tfidf_fallback",
            "fallback_used": True,
            "review_threshold": _DEFAULT_REVIEW_THRESHOLD,
            "force_review": True,
            "input_truncated": False,
        }

    score = float(result["top_class_probability"])
    threshold = float(result.get("review_threshold", _DEFAULT_REVIEW_THRESHOLD))
    fallback_used = bool(result.get("fallback_used", False))
    force_review = bool(result.get("force_review", False))
    intent = str(result["candidate_intent"])
    risk_flags = []
    baseline_intent = None
    baseline_confidence = 0.0
    models_agree: bool | None = None
    if not fallback_used:
        try:
            baseline = run_intent_classifier(safe_message)
            baseline_intent = str(baseline["candidate_intent"])
            baseline_confidence = float(baseline["top_class_probability"])
            models_agree = baseline_intent == intent
            if not models_agree:
                risk_flags.append("classifier_disagreement")
        except Exception:
            risk_flags.append("baseline_corroboration_unavailable")
    if score < threshold:
        risk_flags.append("low_classifier_confidence")
    if fallback_used:
        risk_flags.append("laya_unavailable_baseline_fallback")
    if result.get("input_truncated"):
        risk_flags.append("classifier_input_truncated")
    if result.get("laya_abstained"):
        risk_flags.append("laya_abstained")
    if intent == "other_or_unsupported":
        risk_flags.append("unsupported_or_unclear_intent")

    consensus_routing_enabled = os.getenv("CLASSIFIER_CONSENSUS_ROUTING_ENABLED", "false").strip().lower() == "true"
    try:
        baseline_threshold = float(os.getenv("CLASSIFIER_BASELINE_MIN_CONFIDENCE", "0.60"))
    except ValueError as exc:
        raise ValueError("CLASSIFIER_BASELINE_MIN_CONFIDENCE must be numeric") from exc
    if not 0.0 <= baseline_threshold <= 1.0:
        raise ValueError("CLASSIFIER_BASELINE_MIN_CONFIDENCE must be between 0 and 1")
    automatic_routing_enabled = bool(
        consensus_routing_enabled
        and not fallback_used
        and not force_review
        and models_agree is True
        and score >= threshold
        and baseline_confidence >= baseline_threshold
        and intent != "other_or_unsupported"
    )
    needs_review = not automatic_routing_enabled
    if not consensus_routing_enabled:
        risk_flags.append("automatic_routing_disabled_by_policy")
    triage_status = "needs_review" if needs_review else "ready"
    return TicketClassification.model_validate({
        "intent": intent,
        "confidence": score,
        "classifier_version": result["model_version"],
        "classifier_provider": result.get("provider", "laya"),
        "fallback_used": fallback_used,
        "triage_status": triage_status,
        "risk_flags": risk_flags,
        "entities": entities,
        "review_threshold": threshold,
        "needs_human_review": needs_review,
        "baseline_intent": baseline_intent,
        "models_agree": models_agree,
        "confidence_calibrated": False,
        "automatic_routing_enabled": automatic_routing_enabled,
    }).model_dump(mode="json")
