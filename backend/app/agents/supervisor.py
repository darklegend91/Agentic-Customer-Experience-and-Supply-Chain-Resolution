"""Allowlisted supervisor routing from Laya's intent to a specialist stage."""

from __future__ import annotations

from typing import Any


INTENT_TO_SPECIALIST = {
    "general_policy": "policy_faq",
    "order_status": "order_delivery",
    "delivery_delay": "order_delivery",
    "delivery_dispute": "order_delivery",
    "non_delivery": "order_delivery",
    "partial_delivery": "order_delivery",
    "address_change": "order_delivery",
    "order_cancellation": "order_delivery",
    "payment_question": "order_delivery",
    "price_difference": "order_delivery",
    "invoice_request": "order_delivery",
    "return_eligibility": "return_refund",
    "return_status": "return_refund",
    "return_pickup": "return_refund",
    "refund_status": "return_refund",
    "late_refund": "return_refund",
    "compensation_request": "return_refund",
    "damaged_item": "product_issue",
    "incorrect_item": "product_issue",
    "missing_accessory": "product_issue",
    "exchange_request": "product_issue",
    "product_question": "product_issue",
    "loyalty_points": "loyalty_rewards",
    "reward_expiry": "loyalty_rewards",
    "reward_redemption": "loyalty_rewards",
}


def route_intent(intent: str | None, *, triage_ready: bool) -> str:
    """Route only trusted predictions; other cases go directly to human review."""
    if not triage_ready:
        return "manual_review"
    return INTENT_TO_SPECIALIST.get(str(intent or ""), "manual_review")


def supervisor_route(state: dict[str, Any]) -> dict[str, Any]:
    classification = state.get("classification") or {}
    triage_ready = bool(state.get("triage_ready"))
    specialist = route_intent(
        classification.get("intent"),
        triage_ready=triage_ready,
    )
    return {"specialist": specialist}
