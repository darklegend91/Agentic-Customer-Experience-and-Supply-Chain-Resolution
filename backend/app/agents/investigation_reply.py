"""Apply the workflow's existing evidence rules to direct-tool chat replies."""

from typing import Any

from ..domain.resolution_rules import ORDER_REQUIRED_INTENTS, evaluate_resolution
from ..domain.support_messages import cannot_answer, unrecognized_package_clarification
from ..guardrails.output_validation import validate_draft
from ..guardrails.evidence_validation import validate_evidence_ledger
from .response_generation import canonical_answer, draft_grounded_response, recorded_claims
from .policy_retrieval import policy_evidence_references


def investigation_reply(result: dict[str, Any], *, message: str, order_id: str | None, locale: str) -> dict[str, Any]:
    classification = result.get("classification") or {}
    intent = classification.get("intent")
    flags = classification.get("risk_flags") or []
    missing = list(result.get("missing_information") or [])
    codes = []
    if "unsupported_account_request" in flags:
        codes = ["unsupported_account_request"]
    elif classification.get("triage_status") == "security_review":
        codes = ["unsafe_input"]
    elif intent == "unrecognized_package":
        return {
            "status": "needs_information",
            "answer": unrecognized_package_clarification(order_id),
            "reason_codes": ["unrecognized_package_needs_confirmation"],
            "evidence_refs": [],
        }
    elif intent == "other_or_unsupported":
        codes = ["unsupported_request"]
    elif intent in ORDER_REQUIRED_INTENTS and not order_id:
        codes = ["order_id_required"]
        missing = sorted(set(missing + ["order_id"]))
    if codes:
        return {"status": "needs_information" if "order_id_required" in codes else "escalated",
                "answer": cannot_answer(codes, missing), "reason_codes": codes, "evidence_refs": []}

    state = {"message": message, "order_id": order_id, "classification": classification, "locale": locale,
             "evidence": {"order": result.get("order_evidence"), "policy": result.get("policy_evidence"),
                          "customer_context": result.get("customer_context"), "ledger": result.get("evidence_ledger")},
             "missing_information": missing}
    collected_refs = set(policy_evidence_references(result.get("policy_evidence") or {}))
    for source in (result.get("order_evidence") or {}, result.get("customer_context") or {}):
        for values in (source.get("evidence_refs") or {}).values():
            if isinstance(values, list):
                collected_refs.update(value for value in values if isinstance(value, str))
    refs = sorted(collected_refs)
    state["evidence_refs"] = refs
    resolution = evaluate_resolution(state)
    state["resolution"] = resolution
    if resolution.get("outcome") != "answer":
        codes = resolution.get("reason_codes") or ["requires_human_review"]
        missing = resolution.get("missing_information") or missing
        return {"status": "needs_information" if resolution.get("outcome") == "needs_information" else "escalated",
                "answer": cannot_answer(codes, missing), "reason_codes": codes, "evidence_refs": refs}
    try:
        if validate_evidence_ledger(result.get("evidence_ledger") or {}):
            return {"status": "failed_safe", "answer": cannot_answer(["evidence_validation_failed"]),
                    "reason_codes": ["evidence_validation_failed"], "evidence_refs": []}
        drafted = draft_grounded_response(state)
        draft = drafted.get("draft") or {}
        claims = recorded_claims(state)
        errors = validate_draft(draft, set(refs), answer_required=True, expected_claims=claims,
                                expected_answer=canonical_answer(state, claims) if drafted.get("draft_provider") != "groq" else None)
        if drafted.get("draft_error_code") or errors:
            raise ValueError("Verified response could not be produced")
    except Exception:
        return {"status": "failed_safe", "answer": cannot_answer(["response_drafting_failed"]),
                "reason_codes": ["response_drafting_failed"], "evidence_refs": []}
    return {"status": "answer_ready", "answer": draft["answer"], "reason_codes": [], "evidence_refs": refs}
