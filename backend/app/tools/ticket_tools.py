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


def explicit_order_status_request(message: str) -> bool:
    """Recognize a whole status-only request; extra clauses always use triage.

    This rule permits reading status, never eligibility or an action. Identifiers
    are still checked against caller scope by the workflow input stage.
    """
    text = _ORDER_ID.sub("", message).strip().casefold()
    if text.startswith("tell me about") and not text.removeprefix("tell me about").strip(" ?.!"):
        return bool(_ORDER_ID.search(message))
    text = re.sub(r"\s+", " ", text).strip(" ?.!:")
    return bool(re.fullmatch(
        r"(?:please |can you |could you )?(?:where is my order|where's my order|"
        r"(?:what is|what's) the status of (?:my |the |this )?order|"
        r"(?:track|locate|check) (?:my |the |this )?order|(?:my |the |this )?order status|"
        r"(?:give me |show me |tell me )?(?:my |the |this )?order status(?: update)?|"
        r"(?:tell me about|show me|give me|check) (?:my|this|the) order(?: details)?"
        r"(?: and what is my order id)?|(?:what is|what's) my order (?:id|number)"
        r"|(?:tell me about this order and what is my order id))",
        text,
    ))


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
        # The model sees only masked text and has no tools. A permissive model
        # verdict can never override this deterministic security rejection.
        try:
            classify_with_laya(mask_sensitive_text(normalized))
        except LayaClassifierError:
            pass
        return TicketClassification.model_validate({
            "intent": "other_or_unsupported",
            "confidence": 0.0,
            "classifier_version": "input-guardrail-v1",
            "classifier_provider": "input_guardrail",
            "fallback_used": False,
            "triage_status": "security_review",
            "risk_flags": ["possible_instruction_override", "model_safety_check_cannot_override_guardrail"],
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

    safety_passed = result.get("safety_passed") is True
    if safety_passed and explicit_order_status_request(safe_message) and not any(
        entities[key] for key in ("item_ids", "product_ids", "return_ids")
    ) and len(entities["order_ids"]) <= 1:
        return TicketClassification.model_validate({
            "intent": "order_status",
            "confidence": 1.0,
            "classifier_version": "explicit-order-status-v1",
            "classifier_provider": "deterministic_rule",
            "fallback_used": False,
            "triage_status": "ready",
            "risk_flags": ["explicit_read_only_status_request", "model_safety_check_passed"],
            "entities": entities,
            "review_threshold": _DEFAULT_REVIEW_THRESHOLD,
            "needs_human_review": False,
            "automatic_routing_enabled": True,
            "confidence_calibrated": False,
        }).model_dump(mode="json")
    score = float(result["top_class_probability"])
    threshold = float(result.get("review_threshold", _DEFAULT_REVIEW_THRESHOLD))
    fallback_used = bool(result.get("fallback_used", False))
    force_review = bool(result.get("force_review", False))
    intent = str(result["candidate_intent"])
    risk_flags = []
    if not safety_passed:
        force_review = True
        risk_flags.append("model_safety_check_not_passed")
    baseline_intent = None
    baseline_confidence = 0.0
    models_agree: bool | None = None
    consensus_routing_enabled = os.getenv("CLASSIFIER_CONSENSUS_ROUTING_ENABLED", "false").strip().lower() == "true"
    try:
        baseline_threshold = float(os.getenv("CLASSIFIER_BASELINE_MIN_CONFIDENCE", "0.60"))
    except ValueError as exc:
        raise ValueError("CLASSIFIER_BASELINE_MIN_CONFIDENCE must be numeric") from exc
    if not 0.0 <= baseline_threshold <= 1.0:
        raise ValueError("CLASSIFIER_BASELINE_MIN_CONFIDENCE must be between 0 and 1")

    if not fallback_used:
        try:
            baseline = run_intent_classifier(safe_message)
            baseline_intent = str(baseline["candidate_intent"])
            baseline_confidence = float(baseline["top_class_probability"])
            models_agree = baseline_intent == intent
            if not models_agree:
                if baseline_confidence >= baseline_threshold:
                    risk_flags.append("classifier_disagreement")
                else:
                    # Weak baseline (< threshold) is uncalibrated noise and should not veto Laya
                    models_agree = True
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

    automatic_routing_enabled = bool(
        consensus_routing_enabled
        and not fallback_used
        and not force_review
        and (models_agree is True or baseline_confidence < baseline_threshold)
        and score >= threshold
        and intent != "other_or_unsupported"
    )
    needs_review = not automatic_routing_enabled
    if not consensus_routing_enabled:
        risk_flags.append("automatic_routing_disabled_by_policy")
    triage_status = "security_review" if not safety_passed else ("needs_review" if needs_review else "ready")
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
