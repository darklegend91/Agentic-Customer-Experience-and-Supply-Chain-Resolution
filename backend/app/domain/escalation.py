"""Shared fail-closed result constructors for policy-dependent decisions."""

from __future__ import annotations

from typing import Any, Literal


RuleOutcome = Literal["needs_information", "escalate"]


def require_human_review(
    reason_code: str,
    *,
    outcome: RuleOutcome = "escalate",
    missing_information: list[str] | None = None,
    evidence_refs: list[str] | None = None,
) -> dict[str, Any]:
    """Build a consistent non-authorizing rule result.

    This helper never decides eligibility and never creates an executable action.
    """
    return {
        "outcome": outcome,
        "reason_codes": [reason_code],
        "missing_information": sorted(set(missing_information or [])),
        "requires_approval": False,
        "proposal": None,
        "evidence_refs": sorted(set(evidence_refs or [])),
        "decision": "not_determined",
    }


def evidence_references(state: dict[str, Any]) -> list[str]:
    """Return only the workflow's already collected provenance references."""
    values = state.get("evidence_refs") or []
    return sorted({str(value) for value in values if isinstance(value, str) and value})
