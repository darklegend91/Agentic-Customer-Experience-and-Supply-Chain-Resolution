"""Fail-closed refund eligibility assessment, distinct from refund status."""

from __future__ import annotations

from typing import Any

from .escalation import evidence_references, require_human_review


def assess_refund_eligibility(
    state: dict[str, Any],
    *,
    applicable_policy_hits: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Check evidence completeness, then escalate without approved rule data.

    A return/refund status record is evidence of recorded state, not proof that
    another refund is owed or that a timeline has been breached.
    """
    evidence = state.get("evidence") or {}
    order_evidence = evidence.get("order") or {}
    order = order_evidence.get("order") or {}
    return_rows = order_evidence.get("returns_refunds") or []
    refs = evidence_references(state)

    if not state.get("order_id"):
        return require_human_review(
            "refund_eligibility_requires_order",
            outcome="needs_information",
            missing_information=["order_id"],
            evidence_refs=refs,
        )
    if order_evidence.get("status") == "not_found" or not isinstance(order, dict) or not order:
        return require_human_review("refund_order_record_unavailable", evidence_refs=refs)
    if not return_rows:
        return require_human_review(
            "refund_or_return_record_unavailable",
            missing_information=["return_refund_record"],
            evidence_refs=refs,
        )
    if not any(row.get("refund_status") or row.get("status") for row in return_rows):
        return require_human_review(
            "refund_status_fields_unavailable",
            missing_information=["refund_status"],
            evidence_refs=refs,
        )

    applicable_policy_hits = applicable_policy_hits or []
    if not applicable_policy_hits:
        return require_human_review("no_approved_applicable_refund_policy", evidence_refs=refs)

    has_machine_rule = any(
        isinstance(hit.get("decision_rules"), dict)
        and isinstance(hit["decision_rules"].get("refund_eligibility"), dict)
        for hit in applicable_policy_hits
    )
    if not has_machine_rule:
        return require_human_review(
            "approved_policy_has_no_machine_readable_refund_rule",
            evidence_refs=refs,
        )

    # This codebase does not yet define or execute a reviewed refund rule DSL.
    return require_human_review(
        "refund_rule_interpreter_unavailable",
        evidence_refs=refs,
    )
