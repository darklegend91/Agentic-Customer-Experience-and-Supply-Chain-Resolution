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

_MISSING_REWARD_CLAIM = re.compile(
    r"(?:\b(?:missing|not credited|not added|did(?: not|n't) receive|never received)\b"
    r".{0,64}\b(?:points?|rewards?)\b)"
    r"|(?:\b(?:points?|rewards?)\b.{0,64}"
    r"\b(?:missing|not credited|not added|did(?: not|n't) receive|never received)\b)",
    flags=re.IGNORECASE,
)

_LOYALTY_SUBJECT = re.compile(r"\b(?:points?|rewards?)\b", flags=re.IGNORECASE)
_MUTATION_VERB = re.compile(
    r"\b(?:add|credit|adjust|reinstate|restore|extend|reverse|waive|reissue|issue)\b",
    flags=re.IGNORECASE,
)


def _is_correction_request(message: str) -> bool:
    """Recognize an action request only when it is tied to points or rewards."""
    return bool(
        _REWARD_MUTATION_REQUEST.search(message)
        or _MISSING_REWARD_CLAIM.search(message)
        or (_LOYALTY_SUBJECT.search(message) and _MUTATION_VERB.search(message))
    )


def _active_policy_versions(hits: list[dict[str, Any]]) -> list[str]:
    """Return stable policy references already validated by the evidence ledger."""
    return sorted({
        f"{str(hit.get('policy_id'))}@{str(hit.get('policy_version'))}"
        for hit in hits
        if hit.get("policy_id") and hit.get("policy_version")
    })


def _reversed_earnings_for_order(
    transactions: list[dict[str, Any]], order_id: str,
) -> list[dict[str, Any]]:
    """Find exact, reversible amounts rather than guessing a points correction."""
    matching: list[dict[str, Any]] = []
    for row in transactions:
        if not isinstance(row, dict):
            continue
        if str(row.get("order_id") or "").casefold() != order_id.casefold():
            continue
        if str(row.get("event_type") or "").casefold() != "points_earned":
            continue
        if str(row.get("status") or "").casefold() != "reversed":
            continue
        points = row.get("points_delta")
        if isinstance(points, int) and points > 0:
            matching.append(row)
    return matching


def assess_reward_request(
    state: dict[str, Any], *, applicable_policy_hits: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
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
    applicable_policy_hits = applicable_policy_hits or []

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
    correction_requested = _is_correction_request(message)
    if correction_requested:
        # A customer report is never enough to invent a credit. A draft is
        # possible only when the ledger contains an exact reversed earning for
        # this delivered order and an active, applicable policy permits review.
        if not applicable_policy_hits:
            return require_human_review(
                "reward_action_requires_approved_rule_and_human_review",
                evidence_refs=refs,
            )
        order = order_evidence.get("order") or {}
        if str(order.get("status") or "").casefold() != "delivered":
            return require_human_review(
                "reward_correction_requires_delivered_order",
                evidence_refs=refs,
            )
        reversed_earnings = _reversed_earnings_for_order(transactions, str(state["order_id"]))
        if not reversed_earnings:
            return require_human_review(
                "reward_correction_amount_not_provable_from_ledger",
                outcome="needs_information",
                missing_information=["reversed_points_earned_transaction"],
                evidence_refs=refs,
            )
        points_delta = sum(int(row["points_delta"]) for row in reversed_earnings)
        event_ids = [str(row.get("event_id")) for row in reversed_earnings if row.get("event_id")]
        policy_versions = _active_policy_versions(applicable_policy_hits)
        if not policy_versions:
            return require_human_review(
                "reward_action_requires_approved_rule_and_human_review",
                evidence_refs=refs,
            )
        proposal = {
            "action_kind": "loyalty_reinstatement_review_simulation",
            "summary": (
                f"Review a simulated reinstatement of {points_delta} recorded reversed loyalty points "
                f"for order {state['order_id']}. Approval records a simulation only; it does not "
                "change the customer's rewards balance."
            ),
            "permitted_options": ["approve_simulation", "reject"],
            "evidence_refs": refs,
            "policy_versions": policy_versions,
            "adjustment_draft": {
                "order_id": str(state["order_id"]),
                "account_id": str(account.get("account_id") or ""),
                "points_delta": points_delta,
                "reason_code": "reinstate_reversed_points",
                "source_event_ids": event_ids,
            },
            "action_execution_status": "not_available",
        }
        return {
            "outcome": "proposal",
            "reason_codes": ["verified_reversed_points_eligible_for_human_review"],
            "missing_information": [],
            "requires_approval": True,
            "proposal": proposal,
            "evidence_refs": refs,
            "decision": "human_review_only",
        }

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
