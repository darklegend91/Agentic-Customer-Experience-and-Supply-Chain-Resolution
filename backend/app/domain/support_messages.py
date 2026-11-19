"""Reviewed conversational explanations for requests this app cannot answer."""

import re

SUPPORT_SCOPE = "I can help with orders, deliveries, returns, refunds, product issues, and rewards."
_ACCOUNT_ACCESS = re.compile(
    r"\b(?:reset|change|forgot|forgotten|recover)\b.{0,40}\bpassword\b|"
    r"\bpassword\b.{0,30}\b(?:reset|recovery|change|forgot|recover)\b|"
    r"\b(?:unlock|recover)\s+my\s+account\b", re.IGNORECASE,
)
_UNRECOGNIZED_PACKAGE = re.compile(
    r"\b(?:unrecognised|unrecognized|unknown|unsolicited)\s+(?:package|parcel|delivery|order)\b|"
    r"\b(?:i\s+)?(?:have\s+)?(?:receiv(?:e|ed)|reciev(?:e|ed)|got)\s+(?:a\s+)?"
    r"(?:package|parcel|som(?:e)?thing|item|delivery)\s+(?:that\s+)?(?:i\s+)?"
    r"(?:did(?:\s+not|n't)|have\s+not|haven'?t)\s+order(?:ed)?\b|"
    r"\b(?:this|the)\s+(?:package|parcel|delivery|order)\s+(?:is\s+)?not\s+mine\b",
    re.IGNORECASE,
)


def account_access_request(message: str) -> bool:
    return bool(_ACCOUNT_ACCESS.search(message))


def unrecognized_package_request(message: str) -> bool:
    """Recognize a parcel that may not relate to any customer order.

    This deliberately excludes a known order with a different product, which
    belongs to the separate ``incorrect_item`` flow.
    """
    return bool(_UNRECOGNIZED_PACKAGE.search(message))


def unrecognized_package_clarification(order_id: str | None) -> str:
    if order_id:
        return (
            f"I can help check whether the package relates to order {order_id}. "
            "Do you mean it is for this order but contains a different item, or that it is not "
            "connected to any order you placed? Please confirm the order ID on the shipping label "
            "and describe the item you received."
        )
    return (
        "I can help check whether the package relates to an order you placed. "
        "Is it a package for one of your orders but with a different item, or is it not connected "
        "to any order you placed? Please share the order ID on the shipping label and describe the item you received."
    )


def cannot_answer(reason_codes: list[str], missing_information: list[str] | None = None) -> str:
    codes = set(reason_codes)
    if "unsupported_account_request" in codes:
        return ("I can't reset passwords or access account credentials in this chat. "
                "Please use the password-reset option on the sign-in page, or contact account support.")
    if codes & {"unsafe_input", "possible_instruction_override", "model_safety_check_not_passed"}:
        return ("I can't follow requests to ignore instructions or bypass safety checks. "
                + SUPPORT_SCOPE + " Please describe the customer-support issue you need help with.")
    if codes & {"unsupported_or_unclear_intent", "unsupported_request"}:
        return ("I can't answer that request in this customer-support chat. " + SUPPORT_SCOPE
                + " Tell me which of those you need help with.")
    if "order_record_not_found" in codes:
        return ("I couldn't find that order in the available records. "
                "Please check the order ID and try again.")
    if "source_evidence_stale_or_timestamp_invalid" in codes:
        return ("I can't verify this because the available records aren't current enough. "
                "A support specialist needs to refresh and review the records before answering.")
    if "order_id" in (missing_information or []) or "order_id_required" in codes:
        return ("I can help check that, but I need your order ID first. "
                "Please share the order ID and briefly describe the issue.")
    if codes & {"dependency_unavailable", "response_validation_failed", "response_drafting_failed"}:
        return ("I can't access the information needed to answer right now. "
                "Please try again shortly, or contact a support specialist if the issue is urgent.")
    if codes & {"no_approved_applicable_policy", "policy_answer_requires_human_review"}:
        return ("I can't confirm an answer because an approved policy for this request isn't available. "
                "A support specialist needs to review it before any decision can be made.")
    if missing_information:
        return ("I don't have enough verified information to answer that yet. "
                "Please describe what happened and which item is affected. "
                "A support specialist may need to check the missing records or details.")
    return ("I can't confirm an answer from the verified information available. "
            "A support specialist needs to review this request. No changes have been made to your order.")
