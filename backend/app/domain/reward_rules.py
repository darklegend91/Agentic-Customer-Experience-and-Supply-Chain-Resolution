"""Deterministic read-only reward checks and fail-closed reward action rules."""

from __future__ import annotations

import re
from typing import Any

from .escalation import evidence_references, require_human_review


_REWARD_MUTATION_REQUEST = re.compile(
    r"\b(?:add|credit|adjust|reinstate|restore|extend|reverse|waive|reissue|issue)\b.{0,48}\b(?:points?|rewards?|expiry|expiration)\b|"
    r"\b(?:can i|am i|do i qualify|eligible|eligibility|qualify|want to|please)\b.{0,64}\b(?:redeem|use points|claim a reward)\b",
    flags=re.IGNORECASE,
)


def assess_reward_request(state: dict[str, Any]) -> dict[str, Any]:
    """Allow complete ledger fact lookups; escalate eligibility and mutations."""
    classification = state.get("classification") or {}
    intent = str(classification.get("intent") or "")
    message = str(state.get("message") or "")
    evidence = state.get("evidence") or {}
    order_evidence = evidence.get("order") or {}
    context = evidence.get("customer_context") or {}
    account = context.get("loyalty_account")
    transactions = context.get("loyalty_transactions") or []
    missing = list(context.get("missing_fields") or [])
    conflicts = list(context.get("conflicts") or [])
    refs = evidence_references(state)

    if not state.get("order_id"):
        return require_human_review(
            "reward_lookup_requires_order",
            outcome="needs_information",
            missing_information=["order_id"],
            evidence_refs=refs,
        )
    if order_evidence.get("status") != "found":
        return require_human_review("reward_order_record_unavailable", evidence_refs=refs)
    if context.get("status") == "unavailable":
        return require_human_review(
            "reward_ledger_unavailable",
            missing_information=["customer_context_source"],
            evidence_refs=refs,
        )
    if context.get("status") != "found" or not isinstance(account, dict):
        return require_human_review(
            "reward_account_unavailable",
            outcome="needs_information",
            missing_information=["loyalty_account"],
            evidence_refs=refs,
        )
    if conflicts:
        return require_human_review("reward_ledger_conflict", evidence_refs=refs)
    if "loyalty_transactions_truncated" in set(missing):
        return require_human_review("reward_ledger_truncated", evidence_refs=refs)
    if missing:
        return require_human_review(
            "reward_ledger_incomplete",
            missing_information=missing,
            evidence_refs=refs,
        )
    if _REWARD_MUTATION_REQUEST.search(message):
        return require_human_review(
            "reward_action_requires_approved_rule_and_human_review",
            evidence_refs=refs,
        )

    if intent == "loyalty_points":
        return {
            "outcome": "answer",
            "reason_codes": ["read_only_reward_balance_available"],
            "missing_information": [],
            "requires_approval": False,
            "proposal": None,
            "evidence_refs": refs,
            "decision": "recorded_facts_only",
        }

    if intent == "reward_expiry":
        return {
            "outcome": "answer",
            "reason_codes": ["read_only_reward_expiry_records_available"],
            "missing_information": [],
            "requires_approval": False,
            "proposal": None,
            "evidence_refs": refs,
            "decision": "recorded_facts_only",
        }

    if intent == "reward_redemption":
        # A ledger lookup may report a recorded redemption or its absence. It
        # never grants a redemption or decides whether the customer qualifies.
        return {
            "outcome": "answer",
            "reason_codes": ["read_only_redemption_status_lookup"],
            "missing_information": [],
            "requires_approval": False,
            "proposal": None,
            "evidence_refs": refs,
            "decision": "recorded_facts_only",
        }

    return require_human_review("unsupported_reward_rule_request", evidence_refs=refs)
