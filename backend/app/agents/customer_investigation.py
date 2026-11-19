"""Read-only LangGraph specialist for an authorized customer with no selected order."""

from __future__ import annotations

import re
from typing import Any

from ..db.repositories import RecordNotFound, get_customer_orders_readonly, get_customer_support_context_readonly
from ..db.session import DatabaseUnavailable
from ..domain.customer_references import CUSTOMER_REFERENCE
from ..domain.support_messages import account_access_request, cannot_answer, unrecognized_package_clarification, unrecognized_package_request
from ..guardrails.content_safety import evidence_risk_codes
from ..guardrails.evidence_validation import build_evidence_ledger, validate_evidence_ledger
from ..guardrails.output_validation import validate_draft
from .sanitization import sanitize_request


def _request_topic(message: str) -> str:
    text = CUSTOMER_REFERENCE.sub("", message).casefold().strip(" \t.?:#")
    if not text or re.fullmatch(r"(?:customer(?:\s+id)?|id|tell me about|look up|investigate|show me)", text):
        return "overview"
    if re.search(r"\b(?:add|adjust|apply|cancel|change|correct|credit|missing|reinstate|restore|reverse)\b", text):
        if re.search(r"\b(?:points|rewards?|loyalty|order|refund|return)\b", text):
            return "order_required"
    if re.search(r"\b(?:refunds?|returns?|replacement|exchange|damaged|item|delivery|package|parcel|shipment|track)\b|\bwhere\b.*\border\b", text):
        return "order_required"
    if re.search(r"\b(?:overview|full investigation|summary)\b|\b(?:show|investigate|look up|tell me about|details)\b.*\bcustomer\b", text):
        return "overview"
    if re.search(r"\b(?:prior contact|support history|contact history|previous tickets|communications?)\b", text):
        return "history"
    if re.search(r"\b(?:rewards?|points|loyalty)\b", text):
        if re.search(r"\bexpir\w*\b", text):
            return "loyalty_expiry"
        if re.search(r"\b(?:redeem\w*|redemption\w*)\b", text):
            return "loyalty_redemptions"
        if re.search(r"\b(?:transactions?|activity|history)\b", text):
            return "loyalty_activity"
        return "loyalty"
    if re.search(r"\b(?:orders|my order|order history|order status|last order|recent order|latest order)\b", text):
        return "orders"
    return "unsupported"


def _result(status: str, answer: str, reason: str | None = None, **fields: Any) -> dict[str, Any]:
    outcome = {"answer_ready": "answer", "needs_information": "needs_information"}.get(status, "escalate")
    codes = [reason] if reason else []
    return {
        "specialist": "customer_investigation",
        "status": status,
        "disposition": outcome,
        "reason_codes": codes,
        "resolution": {"outcome": outcome, "reason_codes": codes},
        "answer": answer,
        **fields,
    }


def investigate_customer(state: dict[str, Any]) -> dict[str, Any]:
    screened = sanitize_request(state)
    if screened.get("input_error_code"):
        return _result("escalated", cannot_answer(["unsafe_input"]), "unsafe_input")
    customer_id = state.get("customer_id")
    allowed = set(state.get("allowed_customer_ids") or [])
    if not customer_id or ("*" not in allowed and customer_id not in allowed):
        return _result("failed_safe", "I can't access this customer with the current permissions.", "customer_scope_denied")
    message = screened["message"] or ""
    if account_access_request(message):
        return _result("escalated", cannot_answer(["unsupported_account_request"]), "unsupported_account_request")
    if unrecognized_package_request(message):
        return _result("needs_information", unrecognized_package_clarification(None),
                       "unrecognized_package_needs_confirmation",
                       missing_information=["shipping_label_order_id", "received_item_description"])
    topic = _request_topic(message)
    if topic == "unsupported":
        return _result(
            "needs_information",
            "What would you like me to check for this customer? I can review recent orders, loyalty, or prior support contacts.",
            "customer_investigation_topic_required", missing_information=["investigation_topic"],
        )
    if topic == "order_required":
        return _result(
            "needs_information",
            "Please share the specific order ID so I can check that issue. I can also show the customer's recent orders.",
            "order_id_required", missing_information=["order_id"],
        )

    try:
        snapshot = get_customer_orders_readonly(customer_id, include_orders=topic in {"overview", "orders"})
    except RecordNotFound:
        return _result("needs_information", "I couldn't find that customer. Please check the customer ID and try again.",
                       "customer_record_not_found", missing_information=["customer_id"])
    except DatabaseUnavailable:
        return _result("failed_safe", cannot_answer(["dependency_unavailable"]), "dependency_unavailable")

    evidence: dict[str, Any] = {}
    if topic in {"overview", "orders"}:
        evidence["customer_orders"] = snapshot
    if topic != "orders":
        try:
            context = get_customer_support_context_readonly(customer_id=customer_id)
        except DatabaseUnavailable:
            context = {"missing_fields": ["customer_context_source"], "status": "insufficient_data"}
        context.pop("order_id", None)
        # Customer-wide contact evidence uses structured metadata only.
        context["prior_communications"] = [
            {key: row[key] for key in ("communication_id", "channel", "occurred_at", "outcome")}
            for row in context.get("prior_communications", [])
        ] if topic in {"overview", "history"} else []
        if topic == "history":
            context["loyalty_account"] = None
        if topic in {"history", "overview", "loyalty"}:
            context["loyalty_transactions"] = []
        evidence["customer_context"] = context
    if evidence_risk_codes(evidence):
        return _result("escalated", cannot_answer(["response_validation_failed"]), "unsafe_evidence")

    ledger = build_evidence_ledger(message=message, ticket_id=state.get("ticket_id"), evidence=evidence)
    evidence["ledger"] = ledger
    claims: list[dict[str, Any]] = []

    def claim(text: str, refs: list[str]) -> None:
        claims.append({"text": text, "evidence_refs": refs})

    if "customer_orders" in evidence:
        for row in snapshot["orders"]:
            status = str(row.get("status") or "status unavailable").replace("_", " ")
            placed = f" (placed {row['order_date']})" if row.get("order_date") else ""
            claim(f"- `{row['order_id']}`{placed} — {status}", [f"order:{row['order_id']}"])
        if not snapshot["orders"]:
            claim("No orders were found in the available records.", ["customer_orders:lookup"])

    context = evidence.get("customer_context") or {}
    refs = context.get("evidence_refs") or {}
    missing = set(context.get("missing_fields") or [])
    context_unavailable = bool(missing & {"customer_context_source", "customer_context_schema_unavailable"})
    account = context.get("loyalty_account") or {}
    if topic != "history" and account and not context.get("conflicts"):
        claim(
            f"The last recorded loyalty balance was {account['points_balance']} points (as of {account['as_of'][:10]}).",
            refs["loyalty_account"],
        )
        if topic.startswith("loyalty_"):
            rows = context.get("loyalty_transactions", [])
            if topic == "loyalty_expiry":
                rows = [row for row in rows if row.get("expires_at")]
            elif topic == "loyalty_redemptions":
                rows = [row for row in rows if row.get("event_type") == "reward_redeemed"]
            if not rows and refs.get("customer_context_lookup"):
                claim("The available snapshot did not return matching loyalty events.", refs["customer_context_lookup"])
            for row in rows[:5]:
                expiry = f", recorded expiry {row['expires_at']}" if row.get("expires_at") else ""
                claim(f"- {row['event_type'].replace('_', ' ')} — {row['points_delta']} points ({row['status']}{expiry})",
                      [f"loyalty_transaction:{row['event_id']}"])
    if topic in {"overview", "history"} and not context_unavailable:
        contacts = context.get("prior_communications", [])
        claim(f"The support history returned {len(contacts)} recent contact record(s).",
              refs["customer_context_lookup"])
        if topic == "history":
            for row in contacts[:5]:
                claim(f"- {row['occurred_at'][:10]} — {row['channel']} ({row['outcome'].replace('_', ' ')})",
                      [f"customer_communication:{row['communication_id']}"])

    if not claims:
        return _result("escalated", "I couldn't verify the requested customer records. A support specialist can review this.",
                       "customer_evidence_unavailable", evidence=evidence)
    sections = []
    if snapshot["orders"] and "customer_orders" in evidence:
        sections.append("Recent orders" + (" (latest five shown)" if snapshot["has_more_orders"] else "") + "\n")
    sections.extend(item["text"] for item in claims)
    if topic == "overview":
        if context_unavailable:
            sections.append("Loyalty and support history are currently unavailable.")
        elif not account or context.get("conflicts"):
            sections.append("I couldn't verify a loyalty balance from the available records.")
    citations = sorted({ref for item in claims for ref in item["evidence_refs"]})
    draft = {"answer": "\n\n".join(sections), "claims": claims, "evidence_refs": citations}
    allowed_refs = {item["source_ref"] for item in ledger["source_facts"]}
    if validate_evidence_ledger(ledger) or validate_draft(draft, allowed_refs, answer_required=True, expected_claims=claims):
        return _result("escalated", cannot_answer(["response_validation_failed"]), "response_validation_failed")
    return _result("answer_ready", draft["answer"], evidence=evidence, evidence_refs=citations,
                   draft=draft, draft_provider="deterministic_template")
