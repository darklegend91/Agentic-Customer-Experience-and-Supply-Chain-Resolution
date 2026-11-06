"""Deterministic evidence gates and non-executing resolution proposal rules."""

from __future__ import annotations

from typing import Any

from .escalation import evidence_references, require_human_review
from .refund_eligibility import assess_refund_eligibility
from .return_eligibility import assess_return_eligibility
from .reward_rules import assess_reward_request


ORDER_REQUIRED_INTENTS = {
    "address_change", "compensation_request", "damaged_item", "delivery_delay",
    "delivery_dispute", "exchange_request", "incorrect_item", "invoice_request",
    "late_refund", "missing_accessory", "non_delivery", "order_cancellation",
    "order_status", "partial_delivery", "payment_question", "price_difference",
    "product_question", "refund_status", "return_eligibility", "return_pickup",
    "return_status", "loyalty_points", "reward_expiry", "reward_redemption",
}

POLICY_REQUIRED_INTENTS = {
    "general_policy", "compensation_request", "damaged_item", "exchange_request",
    "incorrect_item", "return_eligibility", "late_refund",
}

PROPOSAL_INTENTS = {
    "compensation_request": "compensation_review_simulation",
    "damaged_item": "item_remedy_review_simulation",
    "exchange_request": "exchange_review_simulation",
    "incorrect_item": "item_remedy_review_simulation",
}


def _policy_hits(policy_evidence: dict[str, Any]) -> list[dict[str, Any]]:
    results = policy_evidence.get("results") or {}
    return [hit for method_hits in results.values() for hit in (method_hits or [])]


def _authoritative_policy_hits(
    policy_evidence: dict[str, Any],
    *,
    intent: str,
    evidence_ledger: dict[str, Any],
) -> list[dict[str, Any]]:
    applicable_chunks = {
        str(item.get("evidence_id", "")).removeprefix("policy.")
        for item in evidence_ledger.get("policy_statements") or []
        if item.get("applicability") == "applicable"
    }
    return [
        hit for hit in _policy_hits(policy_evidence)
        if hit.get("status") == "active"
        and hit.get("environment_scope") == "production"
        and hit.get("synthetic_demo") is not True
        and bool(hit.get("policy_id"))
        and bool(hit.get("policy_version"))
        and bool(hit.get("source_file_sha256"))
        and intent in set(hit.get("intents") or [])
        and str(hit.get("chunk_id") or "") in applicable_chunks
    ]


def _order_value(order_evidence: dict[str, Any], key: str) -> Any:
    order = order_evidence.get("order")
    return order.get(key) if isinstance(order, dict) else None


def _relevant_order_status(state: dict[str, Any], intent: str) -> tuple[str | None, list[str]]:
    evidence = state.get("evidence") or {}
    order_evidence = evidence.get("order")
    missing: list[str] = []
    if not state.get("order_id"):
        return None, ["order_id"]
    if not isinstance(order_evidence, dict):
        return None, ["order_evidence"]
    if order_evidence.get("status") == "not_found":
        return "not_found", ["order_record"]
    if not isinstance(order_evidence.get("order"), dict):
        return None, ["order_record"]

    if intent in {"order_status", "order_cancellation", "address_change", "price_difference", "payment_question", "invoice_request"}:
        if not _order_value(order_evidence, "status"):
            missing.append("order.status")
    elif intent in {"delivery_delay", "delivery_dispute", "non_delivery", "partial_delivery"}:
        if not order_evidence.get("delivery_events"):
            missing.append("delivery_events")
    elif intent in {"return_status", "return_pickup", "refund_status"}:
        # A successful, scoped empty lookup is valid evidence that no record was found.
        pass
    elif intent in {"return_eligibility", "damaged_item", "incorrect_item", "missing_accessory", "exchange_request", "product_question"}:
        if not order_evidence.get("items"):
            missing.append("order_items")
    elif intent in {"loyalty_points", "reward_expiry", "reward_redemption"}:
        context = evidence.get("customer_context") or {}
        if not isinstance(context.get("loyalty_account"), dict):
            missing.append("loyalty_account")
        if context.get("status") == "unavailable":
            missing.append("customer_context_source")
        if context.get("conflicts"):
            missing.append("loyalty_ledger_consistency")
        if "loyalty_transactions_truncated" in (context.get("missing_fields") or []):
            missing.append("loyalty_transactions_truncated")
    return ("found" if not missing else None), missing


def _event_conflicts_with_ticket(state: dict[str, Any]) -> bool:
    message = str(state.get("message") or "").casefold()
    if not any(phrase in message for phrase in (
        "not received", "never received", "no parcel", "no package", "haven't found", "did not receive",
    )):
        return False
    order = ((state.get("evidence") or {}).get("order") or {})
    for event in order.get("delivery_events") or []:
        event_type = str(event.get("event_type") or "").casefold()
        if "deliver" in event_type and "attempt" not in event_type:
            return True
    return False


def _not_found_or_missing(order_status: str | None, missing: list[str], refs: list[str]) -> dict[str, Any]:
    if order_status == "not_found":
        return require_human_review("order_record_not_found", evidence_refs=refs)
    if missing:
        return require_human_review(
            "required_order_evidence_missing",
            outcome="needs_information" if "order_id" in missing else "escalate",
            missing_information=missing,
            evidence_refs=refs,
        )
    return {}


def evaluate_resolution(state: dict[str, Any]) -> dict[str, Any]:
    """Return a deterministic safe disposition; never execute an order action."""
    classification = state.get("classification") or {}
    intent = str(classification.get("intent") or "other_or_unsupported")
    evidence = state.get("evidence") or {}
    policy_evidence = evidence.get("policy") or {}
    ledger = evidence.get("ledger") or {}
    refs = evidence_references(state)

    if ledger.get("conflicts"):
        return require_human_review("conflicting_source_evidence", evidence_refs=refs)
    ledger_missing = [
        str(item.get("field"))
        for item in ledger.get("missing_information") or []
        if isinstance(item, dict) and item.get("field")
    ]
    timestamp_issues = [
        field for field in ledger_missing
        if field.endswith(".as_of") or field.endswith(".freshness")
    ]
    relevant_sources = {"Neon Postgres order snapshot"} if intent in ORDER_REQUIRED_INTENTS else set()
    if intent in {"loyalty_points", "reward_expiry", "reward_redemption"}:
        relevant_sources.update({"Customer-context snapshot", "Rewards ledger snapshot"})
    relevant_timestamp_issues = [
        field for field in timestamp_issues
        if any(field.startswith(source) for source in relevant_sources)
    ]
    if relevant_timestamp_issues:
        return require_human_review(
            "source_evidence_stale_or_timestamp_invalid",
            missing_information=relevant_timestamp_issues,
            evidence_refs=refs,
        )
    if classification.get("needs_human_review", True):
        return require_human_review("classifier_requires_human_review", evidence_refs=refs)
    if intent == "other_or_unsupported":
        return require_human_review("unsupported_or_unclear_intent", evidence_refs=refs)

    # These modules distinguish recorded facts from decisions that require an
    # approved, machine-readable rule. Draft passages cannot set eligibility.
    if intent == "return_eligibility":
        return assess_return_eligibility(
            state,
            applicable_policy_hits=_authoritative_policy_hits(
                policy_evidence, intent=intent, evidence_ledger=ledger,
            ),
        )
    if intent == "late_refund":
        return assess_refund_eligibility(
            state,
            applicable_policy_hits=_authoritative_policy_hits(
                policy_evidence, intent=intent, evidence_ledger=ledger,
            ),
        )
    if intent in {"loyalty_points", "reward_expiry", "reward_redemption"}:
        return assess_reward_request(state)

    if intent in ORDER_REQUIRED_INTENTS:
        order_status, missing = _relevant_order_status(state, intent)
        result = _not_found_or_missing(order_status, missing, refs)
        if result:
            return result

    if _event_conflicts_with_ticket(state):
        return require_human_review("delivery_record_conflicts_with_customer_report", evidence_refs=refs)

    authoritative_policy = _authoritative_policy_hits(
        policy_evidence,
        intent=intent,
        evidence_ledger=ledger,
    )
    if intent in POLICY_REQUIRED_INTENTS or intent == "general_policy":
        if not authoritative_policy:
            return require_human_review("no_approved_applicable_policy", evidence_refs=refs)
        if intent == "general_policy":
            # This release has no policy-answer renderer that can verify every
            # clause. Keep the retrieved evidence visible and route to review.
            return require_human_review("policy_answer_requires_human_review", evidence_refs=refs)

        proposal_kind = PROPOSAL_INTENTS.get(intent)
        if proposal_kind:
            policy_versions = sorted({
                f"{hit['policy_id']}@{hit['policy_version']}" for hit in authoritative_policy
            })
            proposal = {
                "action_kind": proposal_kind,
                "summary": (
                    f"Review a simulated {intent.replace('_', ' ')} resolution using the cited policy. "
                    "Approval records a simulation only; it does not change an order, issue money, "
                    "or contact the customer."
                ),
                "permitted_options": ["approve_simulation", "reject"],
                "evidence_refs": refs,
                "policy_versions": policy_versions,
                "action_execution_status": "not_available",
            }
            return {
                "outcome": "proposal",
                "reason_codes": ["consequential_resolution_requires_human_approval"],
                "requires_approval": True,
                "proposal": proposal,
                "evidence_refs": refs,
                "decision": "human_review_only",
            }

        return require_human_review("policy_decision_requires_human_review", evidence_refs=refs)

    safe_fact_intents = {
        "order_status", "delivery_delay", "product_question",
        "return_status", "return_pickup", "refund_status",
    }
    if intent in safe_fact_intents:
        return {
            "outcome": "answer",
            "reason_codes": ["read_only_facts_available"],
            "missing_information": [],
            "requires_approval": False,
            "proposal": None,
            "evidence_refs": refs,
            "decision": "recorded_facts_only",
        }

    if intent in {"order_cancellation", "address_change"}:
        return require_human_review("mutation_not_available_in_read_only_workflow", evidence_refs=refs)
    if intent in {"payment_question", "invoice_request", "price_difference", "partial_delivery"}:
        return require_human_review("required_source_fields_not_available", evidence_refs=refs)
    return require_human_review("insufficient_supported_evidence", evidence_refs=refs)
