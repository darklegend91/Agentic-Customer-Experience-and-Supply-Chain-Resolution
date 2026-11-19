"""Validate response structure, evidence citations, unsupported actions, and PII."""

from __future__ import annotations

import re
from typing import Any
from .content_safety import inspect_text
from ..security.pii_masking import mask_sensitive_text


_UNEXECUTED_ACTION_CLAIM = re.compile(
    r"\b(?:i|we|your account)\s+(?:have|has)\s+(?:issued|processed|approved|sent|booked|initiated|cancelled|canceled|refunded|replaced)\b|"
    r"\b(?:refund|replacement|compensation|cancellation)\s+(?:has been|was)\s+(?:issued|processed|approved|sent|completed)\b",
    flags=re.IGNORECASE,
)
_EMAIL = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", flags=re.IGNORECASE)
_PHONE = re.compile(r"(?<!\d)(?:\+?91[\s-]?)?[6-9]\d{9}(?!\d)")


def validate_draft(
    draft: dict[str, Any],
    allowed_evidence_refs: set[str],
    *,
    answer_required: bool,
    expected_claims: list[dict[str, Any]] | None = None,
    expected_answer: str | None = None,
) -> list[str]:
    errors: list[str] = []
    answer = draft.get("answer")
    if not isinstance(answer, str) or len(answer.strip()) == 0:
        errors.append("empty_answer")
        return errors
    if len(answer) > 4000:
        errors.append("answer_too_long")
    if inspect_text(answer, max_chars=4000).risk_codes:
        errors.append("unsafe_response_content")
    if mask_sensitive_text(answer) != answer:
        errors.append("sensitive_response_content")
    # No response schema currently carries a verified URL allowlist. Plain and
    # Markdown links could become phishing/exfiltration targets when rendered.
    if re.search(r"https?\s*://|\]\s*\(|\bwww\.", inspect_text(answer, max_chars=4000).text, re.IGNORECASE):
        errors.append("unverified_response_link")
    if _UNEXECUTED_ACTION_CLAIM.search(answer):
        errors.append("claims_action_was_executed")
    if _EMAIL.search(answer) or _PHONE.search(answer):
        errors.append("possible_personal_contact_data")

    citations = draft.get("evidence_refs")
    if not isinstance(citations, list) or any(not isinstance(ref, str) for ref in citations):
        errors.append("invalid_evidence_refs")
        citations = []
    if len(citations) != len(set(citations)):
        errors.append("duplicate_evidence_reference")
    unknown_refs = set(citations) - allowed_evidence_refs
    if unknown_refs:
        errors.append("unknown_evidence_reference")
    if answer_required and not citations:
        errors.append("answer_has_no_evidence_citation")

    claims = draft.get("claims", [])
    if not isinstance(claims, list):
        errors.append("invalid_claims")
        claims = []
    for claim in claims:
        if not isinstance(claim, dict) or not isinstance(claim.get("text"), str):
            errors.append("invalid_claim")
            continue
        refs = claim.get("evidence_refs")
        if not isinstance(refs, list) or not refs:
            errors.append("claim_missing_evidence")
            continue
        if any(not isinstance(ref, str) or ref not in allowed_evidence_refs for ref in refs):
            errors.append("claim_has_unknown_evidence")

    if expected_claims is not None:
        def normalize_claims(values: list[dict[str, Any]]) -> list[dict[str, Any]]:
            normalized = []
            for claim in values:
                if not isinstance(claim, dict) or not isinstance(claim.get("text"), str):
                    errors.append("invalid_claim")
                    continue
                refs = claim.get("evidence_refs")
                if not isinstance(refs, list) or any(not isinstance(ref, str) for ref in refs):
                    errors.append("claim_missing_evidence")
                    refs = []
                normalized.append({"text": claim["text"], "evidence_refs": sorted(set(refs))})
            return normalized

        expected_normalized = normalize_claims(expected_claims)
        actual_normalized = normalize_claims(claims)
        if actual_normalized != expected_normalized:
            errors.append("claim_not_exactly_supported_by_source_records")
        expected_citations = {
            ref for claim in expected_normalized for ref in claim["evidence_refs"]
        }
        if set(citations) != expected_citations:
            errors.append("answer_citations_do_not_match_claim_sources")
    if expected_answer is not None and answer.strip() != expected_answer:
        errors.append("answer_contains_unverified_or_rephrased_content")

    return sorted(set(errors))
