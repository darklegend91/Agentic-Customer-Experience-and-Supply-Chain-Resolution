"""Input preparation, read-only evidence tools, and five narrow specialist stages."""

from __future__ import annotations

import re
from typing import Any

from ..security.pii_masking import mask_sensitive_text
from ..tools.order_tools import get_order_investigation
from ..tools.customer_context_tools import get_customer_support_context
from ..tools.policy_tools import PolicyMethod
from ..tools.ticket_tools import get_ticket_details
from .policy_retrieval import policy_evidence_references, retrieve_policy_evidence


_ORDER_ID = re.compile(r"\bORD-ID-[A-Za-z0-9][A-Za-z0-9_-]{3,64}\b", re.IGNORECASE)

SPECIALIST_REQUIREMENTS = {
    # needs_order, needs_policy, read_customer_context, context_required_for_decision
    "policy_faq": (False, True, False, False),
    "order_delivery": (True, False, True, False),
    "return_refund": (True, True, True, False),
    "product_issue": (True, True, True, False),
    "loyalty_rewards": (True, True, True, True),
}


def prepare_input(state: dict[str, Any]) -> dict[str, Any]:
    message = str(state.get("message") or "").strip()
    ticket_id = state.get("ticket_id")
    order_id = state.get("order_id")

    if ticket_id:
        try:
            ticket = get_ticket_details(str(ticket_id))
        except Exception:
            return {"input_error_code": "ticket_lookup_unavailable", "status": "failed_safe"}
        if ticket.get("status") != "found" or not str(ticket.get("message") or "").strip():
            return {"input_error_code": "ticket_not_found_or_empty", "status": "failed_safe"}
        stored_message = str(ticket["message"]).strip()
        if message and message not in {stored_message, mask_sensitive_text(stored_message)}:
            return {"input_error_code": "ticket_message_mismatch", "status": "failed_safe"}
        message = stored_message
        mapped_order_id = ticket.get("order_id")
        if order_id and mapped_order_id and order_id != mapped_order_id:
            return {"input_error_code": "ticket_order_reference_conflict", "status": "failed_safe"}
        order_id = order_id or mapped_order_id

    if not message:
        return {"input_error_code": "ticket_message_required", "status": "failed_safe"}

    found_ids = sorted(set(_ORDER_ID.findall(message)))
    if len(found_ids) > 1:
        return {"input_error_code": "multiple_order_references", "status": "needs_information"}
    if found_ids and order_id and found_ids[0].casefold() != str(order_id).casefold():
        return {"input_error_code": "order_reference_conflict", "status": "needs_information"}
    order_id = order_id or (found_ids[0] if found_ids else None)

    allowed_ticket_ids = set(state.get("allowed_ticket_ids") or [])
    allowed_order_ids = set(state.get("allowed_order_ids") or [])
    if ticket_id and "*" not in allowed_ticket_ids and ticket_id not in allowed_ticket_ids:
        return {"input_error_code": "ticket_scope_denied", "status": "failed_safe"}
    if order_id and "*" not in allowed_order_ids and order_id not in allowed_order_ids:
        return {"input_error_code": "order_scope_denied", "status": "failed_safe"}

    clean_message = mask_sensitive_text(message)
    if not isinstance(clean_message, str) or not clean_message.strip():
        return {"input_error_code": "ticket_message_invalid", "status": "failed_safe"}

    return {
        "message": clean_message[:5000],
        "order_id": order_id,
        "status": "running",
        "input_error_code": None,
    }


def gather_specialist_evidence(state: dict[str, Any], specialist: str) -> dict[str, Any]:
    if specialist not in SPECIALIST_REQUIREMENTS:
        return {"specialist_error_code": "unsupported_specialist", "status": "escalated"}

    needs_order, needs_policy, needs_customer_context, _context_required = SPECIALIST_REQUIREMENTS[specialist]
    evidence: dict[str, Any] = {"order": None, "policy": None, "customer_context": None}
    methods = list(state.get("methods") or ["semantic", "keyword"])
    top_k = int(state.get("top_k") or 3)
    query = str(state.get("query") or state.get("message") or "")

    try:
        if needs_order:
            if state.get("order_id"):
                evidence["order"] = get_order_investigation(str(state["order_id"]))
            else:
                evidence["order"] = {
                    "status": "insufficient_data",
                    "order_id": None,
                    "order": None,
                    "items": [],
                    "delivery_events": [],
                    "returns_refunds": [],
                    "evidence_refs": {},
                    "missing_fields": ["order_id"],
                }
        if needs_customer_context:
            if state.get("order_id"):
                try:
                    evidence["customer_context"] = get_customer_support_context(str(state["order_id"]))
                except Exception as exc:
                    evidence["customer_context"] = {
                        "status": "unavailable",
                        "order_id": state.get("order_id"),
                        "loyalty_account": None,
                        "loyalty_transactions": [],
                        "prior_communications": [],
                        "evidence_refs": {},
                        "missing_fields": ["customer_context_source"],
                        "error_type": type(exc).__name__,
                    }
            else:
                evidence["customer_context"] = {
                    "status": "insufficient_data",
                    "order_id": None,
                    "loyalty_account": None,
                    "loyalty_transactions": [],
                    "prior_communications": [],
                    "evidence_refs": {},
                    "missing_fields": ["order_id"],
                }
        if needs_policy:
            evidence["policy"] = retrieve_policy_evidence(
                query,
                methods=methods,
                top_k=top_k,
                locale=str(state.get("locale") or "en-IN"),
            )
    except Exception as exc:
        # The event records only an error class, not exception text or ticket data.
        return {
            "specialist_error_type": type(exc).__name__,
            "specialist_error_code": "evidence_dependency_unavailable",
            "status": "failed_safe",
            "evidence": evidence,
        }

    refs: set[str] = set()
    order_evidence = evidence.get("order") or {}
    for values in (order_evidence.get("evidence_refs") or {}).values():
        for value in values if isinstance(values, list) else []:
            refs.add(str(value))
    if evidence.get("policy"):
        refs.update(policy_evidence_references(evidence["policy"]))
    context = evidence.get("customer_context") or {}
    context_refs = context.get("evidence_refs") or {}
    for values in context_refs.values():
        if isinstance(values, list):
            refs.update(str(value) for value in values)

    return {
        "evidence": evidence,
        "evidence_refs": sorted(refs),
        "specialist_error_code": None,
        "status": "running",
    }


def policy_faq_specialist(state: dict[str, Any]) -> dict[str, Any]:
    return gather_specialist_evidence(state, "policy_faq")


def order_delivery_specialist(state: dict[str, Any]) -> dict[str, Any]:
    return gather_specialist_evidence(state, "order_delivery")


def return_refund_specialist(state: dict[str, Any]) -> dict[str, Any]:
    return gather_specialist_evidence(state, "return_refund")


def product_issue_specialist(state: dict[str, Any]) -> dict[str, Any]:
    return gather_specialist_evidence(state, "product_issue")


def loyalty_rewards_specialist(state: dict[str, Any]) -> dict[str, Any]:
    return gather_specialist_evidence(state, "loyalty_rewards")
