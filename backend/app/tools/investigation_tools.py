"""Read-only ticket investigation orchestration shared by HTTP and MCP."""

from __future__ import annotations

from typing import Any

from ..api.schemas.ticket import TicketInvestigationResponse
from ..guardrails.evidence_validation import build_evidence_ledger
from ..db.repositories import RecordNotFound
from ..runtime import require_local_development
from .order_tools import get_order_investigation
from .customer_context_tools import get_customer_support_context
from .policy_tools import PolicyMethod, search_policy
from .ticket_tools import classify_ticket_message, get_ticket_details


_ORDER_DEPENDENT_INTENTS = {
    "delivery_delay",
    "non_delivery",
    "order_status",
    "damaged_item",
    "incorrect_item",
    "return_status",
    "refund_status",
    "loyalty_points",
    "reward_expiry",
    "reward_redemption",
    "order_cancellation",
}


def investigate_ticket(
    *,
    ticket_id: str | None = None,
    message: str | None = None,
    order_id: str | None = None,
    query: str | None = None,
    top_k: int = 3,
    methods: list[PolicyMethod] | None = None,
    locale: str = "en-IN",
) -> dict[str, Any]:
    """Combine a ticket triage suggestion with separate SQL and policy evidence."""
    require_local_development()
    if not ticket_id and not message:
        raise ValueError("Provide a ticket_id, a message, or both")

    ticket = None
    if ticket_id:
        ticket = get_ticket_details(ticket_id)
        if ticket["status"] == "not_found":
            raise RecordNotFound("Ticket was not found in the development fixture")
        if not ticket.get("message"):
            raise ValueError("Ticket message is missing; investigation cannot classify it")
        stored_message = ticket["message"]
        if message and message.strip() != stored_message.strip():
            raise ValueError("message does not match the stored ticket")
        message = stored_message
        mapped_order_id = ticket.get("order_id")
        if order_id and mapped_order_id and order_id != mapped_order_id:
            raise ValueError("order_id conflicts with the ticket's mapped order")
        order_id = order_id or mapped_order_id

    assert message is not None
    classification = classify_ticket_message(message)
    extracted_order_ids = classification.get("entities", {}).get("order_ids", [])
    extracted_order_id = extracted_order_ids[0] if len(extracted_order_ids) == 1 else None
    if order_id and extracted_order_id and order_id != extracted_order_id:
        raise ValueError("order_id conflicts with the order reference in the ticket message")
    order_id = order_id or extracted_order_id
    policy_evidence = search_policy(query or message, top_k=top_k, methods=methods, locale=locale)

    order_evidence = None
    if order_id:
        order_evidence = get_order_investigation(order_id)

    customer_context = None
    customer_context_unavailable = False
    if order_id:
        try:
            customer_context = get_customer_support_context(order_id)
        except Exception:
            customer_context_unavailable = True

    missing_information = list(policy_evidence.get("missing_fields", []))
    if order_evidence:
        missing_information.extend(order_evidence.get("missing_fields", []))
    elif not order_id and classification.get("intent") in _ORDER_DEPENDENT_INTENTS:
        missing_information.append("order_id")
    if classification.get("intent") in {"loyalty_points", "reward_expiry", "reward_redemption"}:
        if not customer_context:
            missing_information.append("customer_context_source")
        else:
            missing_information.extend(customer_context.get("missing_fields", []))
            missing_information.extend(customer_context.get("conflicts", []))
    missing_information = sorted(set(missing_information))
    evidence = {
        "order": order_evidence,
        "customer_context": customer_context,
        "policy": policy_evidence,
    }
    evidence_ledger = build_evidence_ledger(
        message=message or "",
        ticket_id=ticket_id,
        classification=classification,
        evidence=evidence,
        missing_information=missing_information,
        locale=locale,
    )
    if evidence_ledger.get("conflicts"):
        missing_information.extend(
            conflict["conflict_id"] for conflict in evidence_ledger["conflicts"]
        )
        missing_information = sorted(set(missing_information))
    result = {
        "evidence_status": "insufficient_data" if missing_information else "found",
        "ticket": ticket,
        "classification": classification,
        "order_evidence": order_evidence,
        "customer_context": customer_context,
        "policy_evidence": policy_evidence,
        "evidence_ledger": evidence_ledger,
        "missing_information": missing_information,
        "limitations": [
            "Classifier output is an uncalibrated review-only suggestion.",
            "Policy passages are synthetic development drafts and do not establish customer eligibility.",
            "Order IDs are not authorization; this local fixture API has no caller identity or ownership checks.",
            "Customer loyalty and communication records are synthetic; an unavailable optional history source is not evidence that no history exists." if customer_context_unavailable else "Customer context includes only bounded, PII-minimized ledger rows and communication summaries.",
        ],
    }
    # Validate the complete internal result before API or MCP serializers see it.
    return TicketInvestigationResponse.model_validate({"request_id": "pending", **result}).model_dump(
        mode="json", exclude={"request_id"}
    )
