"""Fail-closed return eligibility assessment.

The current knowledge base contains draft prose, not approved executable rules.
This module validates the minimum evidence and escalates rather than inferring
an eligibility outcome from a category, damage report, or retrieved paragraph.
"""

from __future__ import annotations

from typing import Any

from .escalation import evidence_references, require_human_review


def assess_return_eligibility(
    state: dict[str, Any],
    *,
    applicable_policy_hits: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    evidence = state.get("evidence") or {}
    order_evidence = evidence.get("order") or {}
    order = order_evidence.get("order") or {}
    items = order_evidence.get("items") or []
    entities = (state.get("classification") or {}).get("entities") or {}
    referenced_item_ids = {str(value) for value in entities.get("item_ids") or []}
    referenced_product_ids = {str(value) for value in entities.get("product_ids") or []}
    refs = evidence_references(state)

    if len(referenced_item_ids) + len(referenced_product_ids) > 2:
        return require_human_review(
            "return_target_item_ambiguous",
            outcome="needs_information",
            missing_information=["target_order_item"],
            evidence_refs=refs,
        )

    if not state.get("order_id"):
        return require_human_review(
            "return_eligibility_requires_order",
            outcome="needs_information",
            missing_information=["order_id"],
            evidence_refs=refs,
        )
    if order_evidence.get("status") == "not_found" or not isinstance(order, dict) or not order:
        return require_human_review("return_order_record_unavailable", evidence_refs=refs)
    if not items:
        return require_human_review(
            "return_item_evidence_unavailable",
            missing_information=["order_items"],
            evidence_refs=refs,
        )
    if not order.get("order_date"):
        return require_human_review(
            "return_purchase_date_unavailable",
            missing_information=["order_date"],
            evidence_refs=refs,
        )

    requested_items = [
        item for item in items
        if (not referenced_item_ids or str(item.get("item_id")) in referenced_item_ids)
        and (not referenced_product_ids or str(item.get("product_id")) in referenced_product_ids)
    ]
    if (referenced_item_ids or referenced_product_ids) and not requested_items:
        return require_human_review(
            "requested_return_item_not_in_order",
            outcome="needs_information",
            missing_information=["order_item_match"],
            evidence_refs=refs,
        )
    if not referenced_item_ids and not referenced_product_ids and len(items) > 1:
        return require_human_review(
            "return_target_item_ambiguous",
            outcome="needs_information",
            missing_information=["target_order_item"],
            evidence_refs=refs,
        )

    applicable_policy_hits = applicable_policy_hits or []
    if not applicable_policy_hits:
        return require_human_review("no_approved_applicable_return_policy", evidence_refs=refs)

    # Retrieved passages are prose. The index currently has no signed,
    # machine-readable return rule contract, so even an approved passage cannot
    # be used as a deterministic eligible/ineligible result.
    has_machine_rule = any(
        isinstance(hit.get("decision_rules"), dict)
        and isinstance(hit["decision_rules"].get("return_eligibility"), dict)
        for hit in applicable_policy_hits
    )
    if not has_machine_rule:
        return require_human_review(
            "approved_policy_has_no_machine_readable_return_rule",
            evidence_refs=refs,
        )

    # No rule interpreter is configured in this release. Keep the result
    # non-authorizing until an approved rule schema and evaluator are deployed.
    return require_human_review(
        "return_rule_interpreter_unavailable",
        evidence_refs=refs,
    )
