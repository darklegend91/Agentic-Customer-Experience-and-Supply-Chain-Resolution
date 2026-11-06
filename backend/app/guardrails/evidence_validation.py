"""Build a typed evidence ledger and fail closed on unusable provenance."""

from __future__ import annotations

import os
from datetime import date, datetime, timezone
from typing import Any

from ..api.schemas.evidence import EvidenceLedger


def _parse_time(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


def _freshness_seconds() -> int:
    try:
        value = int(os.getenv("EVIDENCE_MAX_AGE_SECONDS", "86400"))
    except ValueError as exc:
        raise ValueError("EVIDENCE_MAX_AGE_SECONDS must be an integer") from exc
    if not 60 <= value <= 31_536_000:
        raise ValueError("EVIDENCE_MAX_AGE_SECONDS must be between 60 and 31536000")
    return value


def _field_map(refs: dict[str, Any], field: str) -> list[str]:
    values = refs.get(field) if isinstance(refs, dict) else []
    return [str(value) for value in values] if isinstance(values, list) else []


def _policy_applicability(
    hit: dict[str, Any],
    marketplace: str | None,
    intent: str | None,
    locale: str,
    at: date,
) -> tuple[str, str]:
    # Per docs/policy_schema.md, `approved` is not necessarily effective yet;
    # only `active` means approved and effective for current decisions.
    if hit.get("status") != "active":
        return "not_applicable", "Policy is not in the active lifecycle state."
    if hit.get("environment_scope") != "production" or hit.get("synthetic_demo") is True:
        return "not_applicable", "Policy is synthetic or outside production scope."
    if not hit.get("policy_id") or not hit.get("policy_version") or not hit.get("source_file_sha256"):
        return "unknown", "Required policy identity or provenance metadata is missing."
    policy_marketplace = str(hit.get("marketplace") or "")
    if marketplace and policy_marketplace != marketplace:
        return "not_applicable", "Policy marketplace does not match the order marketplace."
    policy_intents = hit.get("intents") or []
    if not isinstance(policy_intents, list) or not policy_intents:
        return "unknown", "Policy has no intent-scope metadata."
    if intent and intent not in {str(value) for value in policy_intents}:
        return "not_applicable", "Policy intent scope does not match the classified request."
    policy_locale = str(hit.get("locale") or "").strip()
    if not policy_locale:
        return "unknown", "Policy has no locale metadata."
    if policy_locale.casefold() != locale.casefold():
        return "not_applicable", "Policy locale does not match the ticket locale."
    expected_jurisdiction = locale.rsplit("-", maxsplit=1)[-1].upper()
    policy_jurisdiction = str(hit.get("jurisdiction") or "").strip().upper()
    if not policy_jurisdiction or policy_jurisdiction == "TEST":
        return "unknown", "Policy has no verified production jurisdiction."
    if policy_jurisdiction != expected_jurisdiction:
        return "not_applicable", "Policy jurisdiction does not match the ticket locale."
    start_raw = str(hit.get("effective_from") or "").strip()
    end_raw = str(hit.get("effective_to") or "").strip()
    if not start_raw:
        return "unknown", "Policy has no effective-from date."
    try:
        start = date.fromisoformat(start_raw[:10])
        end = date.fromisoformat(end_raw[:10]) if end_raw else None
    except ValueError:
        return "unknown", "Policy effective dates are invalid."
    # effective_to is exclusive by the policy schema.
    if at < start or (end is not None and at >= end):
        return "not_applicable", "Policy is outside its effective date range."
    return "applicable", "Approved policy scope and effective dates match the case."


def build_evidence_ledger(
    *,
    message: str = "",
    ticket_id: str | None = None,
    classification: dict[str, Any] | None = None,
    evidence: dict[str, Any] | None = None,
    missing_information: list[str] | None = None,
    locale: str = "en-IN",
    now: datetime | None = None,
) -> dict[str, Any]:
    """Separate source records, policy passages, reports, assumptions and gaps.

    A source record is verified only as a record returned by its named system;
    this function does not claim the source system's real-world data is correct.
    """
    state = evidence or {}
    order_evidence = state.get("order") or {}
    customer_context = state.get("customer_context") or {}
    policy_evidence = state.get("policy") or {}
    classification = classification or {}
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    now_iso = now.isoformat(timespec="seconds").replace("+00:00", "Z")
    facts: list[dict[str, Any]] = []
    policies: list[dict[str, Any]] = []
    reports: list[dict[str, Any]] = []
    assumptions: list[dict[str, Any]] = []
    missing: dict[str, dict[str, Any]] = {}
    conflicts: list[dict[str, Any]] = []

    def add_fact(evidence_id: str, label: str, value: Any, ref: str, *, source: str, observed_at: str | None = None) -> None:
        facts.append({
            "evidence_id": evidence_id,
            "label": label,
            "value": value,
            "source_system": source,
            "source_ref": ref,
            "observed_at": observed_at,
            "verification": "source_record",
            "applicability": "unknown",
            "explanation": "Verified as a record returned by this source; not independently verified against the real world.",
        })

    def add_missing(field: str, reason: str, source_system: str | None = None) -> None:
        missing[field] = {"field": field, "reason": reason, "source_system": source_system}

    order_as_of = order_evidence.get("as_of")
    order_ref_map = order_evidence.get("evidence_refs") or {}
    order = order_evidence.get("order") or {}
    order_id = str(order_evidence.get("order_id") or order.get("order_id") or "")
    if isinstance(order, dict) and order and not order_as_of:
        add_missing(
            "Neon Postgres order snapshot.as_of",
            "The order source did not provide a snapshot timestamp.",
            "Neon Postgres",
        )
    if isinstance(order, dict) and order:
        ref = (_field_map(order_ref_map, "order") or [f"order:{order_id}"])[0]
        for key in ("status", "order_date", "estimated_delivery", "actual_delivery", "marketplace"):
            if order.get(key) is not None:
                add_fact(f"order.{key}", f"Order {key.replace('_', ' ')}", order[key], ref, source="Neon Postgres", observed_at=order_as_of)
    for group, rows, id_key, system, observed_key in (
        ("items", order_evidence.get("items") or [], "item_id", "Neon Postgres", None),
        ("delivery_events", order_evidence.get("delivery_events") or [], "event_id", "Neon Postgres", "event_time"),
        ("returns_refunds", order_evidence.get("returns_refunds") or [], "return_id", "Neon Postgres", "requested_at"),
    ):
        refs = _field_map(order_ref_map, group)
        for index, row in enumerate(rows):
            if not isinstance(row, dict):
                continue
            ref = refs[index] if index < len(refs) else f"{group}:{row.get(id_key, 'unknown')}"
            add_fact(
                f"{group}.{row.get(id_key, index)}",
                group.replace("_", " ").rstrip("s").title(),
                row,
                ref,
                source=system,
                observed_at=row.get(observed_key) if observed_key else order_as_of,
            )

    loyalty_account = customer_context.get("loyalty_account")
    context_refs = customer_context.get("evidence_refs") or {}
    lookup_refs = _field_map(context_refs, "customer_context_lookup")
    if customer_context.get("status") == "found" and not customer_context.get("as_of"):
        add_missing(
            "Customer-context snapshot.as_of",
            "The customer-context source did not provide a snapshot timestamp.",
            "Neon Postgres",
        )
    if isinstance(loyalty_account, dict) and not loyalty_account.get("as_of"):
        add_missing(
            "Rewards ledger snapshot.as_of",
            "The rewards ledger did not provide an account snapshot timestamp.",
            "Rewards ledger",
        )
    if lookup_refs:
        add_fact(
            "customer_context.lookup",
            "Customer-context lookup result",
            {
                "status": customer_context.get("status"),
                "loyalty_transaction_count": len(customer_context.get("loyalty_transactions") or []),
                "prior_communication_count": len(customer_context.get("prior_communications") or []),
            },
            lookup_refs[0],
            source="Neon Postgres",
            observed_at=customer_context.get("as_of"),
        )
    if isinstance(loyalty_account, dict):
        ref = (_field_map(context_refs, "loyalty_account") or [f"loyalty_account:{loyalty_account.get('account_id', 'unknown')}"])[0]
        add_fact("loyalty.account", "Loyalty account snapshot", loyalty_account, ref, source="Rewards ledger", observed_at=loyalty_account.get("as_of"))
    for group, rows, id_key, time_key in (
        ("loyalty_transactions", customer_context.get("loyalty_transactions") or [], "event_id", "occurred_at"),
        ("prior_communications", customer_context.get("prior_communications") or [], "communication_id", "occurred_at"),
    ):
        refs = _field_map(context_refs, group)
        for index, row in enumerate(rows):
            if not isinstance(row, dict):
                continue
            ref = refs[index] if index < len(refs) else f"{group}:{row.get(id_key, 'unknown')}"
            add_fact(f"{group}.{row.get(id_key, index)}", group.replace("_", " ").title(), row, ref,
                     source="Rewards ledger" if group == "loyalty_transactions" else "Support history",
                     observed_at=row.get(time_key))

    marketplace = order.get("marketplace") if isinstance(order, dict) else None
    intent = str(classification.get("intent") or "") or None
    policy_date = now.date()
    if isinstance(order, dict) and intent in {
        "damaged_item", "incorrect_item", "exchange_request", "return_eligibility", "compensation_request"
    }:
        try:
            if order.get("order_date"):
                policy_date = date.fromisoformat(str(order["order_date"])[:10])
        except ValueError:
            policy_date = now.date()
    for method_hits in (policy_evidence.get("results") or {}).values():
        for hit in method_hits or []:
            if not isinstance(hit, dict):
                continue
            ref = "policy:{document_id}@{version}:{section}:{chunk}".format(
                document_id=hit.get("document_id", "unknown"),
                version=hit.get("policy_version", "unknown"),
                section=hit.get("section_id", "unknown"),
                chunk=hit.get("chunk_id", "unknown"),
            )
            applicability, explanation = _policy_applicability(hit, marketplace, intent, locale, policy_date)
            policies.append({
                "evidence_id": f"policy.{hit.get('chunk_id', 'unknown')}",
                "label": str(hit.get("section_title") or "Retrieved policy passage"),
                "value": {
                    "document_id": hit.get("document_id"),
                    "policy_id": hit.get("policy_id"),
                    "policy_version": hit.get("policy_version"),
                    "status": hit.get("status"),
                    "excerpt": hit.get("excerpt"),
                    "marketplace": hit.get("marketplace"),
                    "jurisdiction": hit.get("jurisdiction"),
                    "locale": hit.get("locale"),
                    "environment_scope": hit.get("environment_scope"),
                    "synthetic_demo": hit.get("synthetic_demo"),
                    "effective_from": hit.get("effective_from"),
                    "effective_to": hit.get("effective_to"),
                    "intents": hit.get("intents") or [],
                    "categories": hit.get("categories") or [],
                    "source_file_sha256": hit.get("source_file_sha256"),
                    "rank": hit.get("rank"),
                    "score": hit.get("score"),
                },
                "source_system": "Milvus policy index",
                "source_ref": ref,
                "observed_at": None,
                "verification": "source_record",
                "applicability": applicability,
                "explanation": explanation,
            })

    if message.strip():
        reports.append({
            "evidence_id": "ticket.customer_report",
            "label": "Customer-reported issue",
            "value": message.strip()[:5000],
            "source_system": "Support ticket",
            "source_ref": f"ticket:{ticket_id}" if ticket_id else "ticket:request",
            "observed_at": now_iso,
            "verification": "customer_report",
            "applicability": "unknown",
            "explanation": "A report from the customer; not an independently verified operational fact.",
        })
    entities = classification.get("entities") or {}
    for order_reference in entities.get("order_ids") or []:
        reports.append({
            "evidence_id": f"ticket.order_reference.{order_reference}",
            "label": "Customer-reported order reference",
            "value": str(order_reference),
            "source_system": "Support ticket",
            "source_ref": f"ticket:{ticket_id}" if ticket_id else "ticket:request",
            "observed_at": now_iso,
            "verification": "customer_report",
            "applicability": "unknown",
            "explanation": "An extracted identifier is a customer-provided lookup hint, not proof of ownership or authorization.",
        })
    if classification.get("intent"):
        assumptions.append({
            "evidence_id": "classification.intent",
            "label": "Predicted primary intent",
            "value": {
                "intent": classification.get("intent"),
                "confidence": classification.get("confidence"),
                "classifier_version": classification.get("classifier_version"),
                "models_agree": classification.get("models_agree"),
            },
            "source_system": str(classification.get("classifier_provider") or "classifier"),
            "source_ref": f"model:{classification.get('classifier_version', 'unknown')}",
            "observed_at": now_iso,
            "verification": "model_inference",
            "applicability": "unknown",
            "explanation": "Intent is a model prediction, not a verified fact. Human review is required when classifiers disagree or routing is disabled.",
        })

    for field in missing_information or []:
        add_missing(str(field), "Required information was not available in the investigation.")
    for field in order_evidence.get("missing_fields") or []:
        add_missing(str(field), "The order source did not return this field.", "Neon Postgres")
    for field in customer_context.get("missing_fields") or []:
        add_missing(str(field), "The customer-context source did not return this field.", "Rewards ledger / support history")
    for conflict in customer_context.get("conflicts") or []:
        conflict_refs = lookup_refs or [f"customer_context:{order_id or 'unknown'}"]
        conflicts.append({
            "conflict_id": "customer_context:" + str(conflict),
            "description": "Customer-context records are internally inconsistent and require human review.",
            "evidence_refs": conflict_refs,
            "resolution": "human_review_required",
        })
    for field in policy_evidence.get("missing_fields") or []:
        add_missing(str(field), "No matching policy passage was returned.", "Milvus policy index")

    max_age = _freshness_seconds()
    for source, stamp in (
        ("Neon Postgres order snapshot", order_as_of),
        ("Customer-context snapshot", customer_context.get("as_of")),
        ("Rewards ledger snapshot", (loyalty_account or {}).get("as_of") if isinstance(loyalty_account, dict) else None),
    ):
        if stamp:
            parsed = _parse_time(stamp)
            if parsed is None:
                add_missing(f"{source}.as_of", "Source timestamp is missing a timezone or is invalid.", source)
            elif (now - parsed).total_seconds() > max_age:
                add_missing(f"{source}.freshness", "Source snapshot exceeds the configured freshness window.", source)
            elif (parsed - now).total_seconds() > 60:
                add_missing(f"{source}.as_of", "Source timestamp is unexpectedly in the future.", source)

    delivered_ref = None
    for index, event in enumerate(order_evidence.get("delivery_events") or []):
        event_type = str(event.get("event_type") or "").casefold()
        if "deliver" in event_type and "attempt" not in event_type:
            refs = _field_map(order_ref_map, "delivery_events")
            delivered_ref = refs[index] if index < len(refs) else f"delivery_event:{event.get('event_id', index)}"
            break
    message_lower = message.casefold()
    report_ref = f"ticket:{ticket_id}" if ticket_id else "ticket:request"
    if delivered_ref and any(phrase in message_lower for phrase in (
        "not received", "never received", "no parcel", "no package", "haven't found", "did not receive",
    )):
        conflicts.append({
            "conflict_id": "delivery_vs_customer_report",
            "description": "A delivery scan is present while the customer reports non-receipt. The scan does not prove the customer received the parcel.",
            "evidence_refs": [delivered_ref, report_ref],
            "resolution": "human_review_required",
        })
    if isinstance(order, dict) and str(order.get("status") or "").casefold() == "cancelled" and delivered_ref:
        order_ref = (_field_map(order_ref_map, "order") or [f"order:{order_id}"])[0]
        conflicts.append({
            "conflict_id": "cancelled_order_has_delivery_scan",
            "description": "The order status is cancelled while a delivered scan is recorded.",
            "evidence_refs": [order_ref, delivered_ref],
            "resolution": "human_review_required",
        })

    ledger = {
        "status": "conflict" if conflicts else "incomplete" if missing else "complete",
        "source_facts": facts,
        "policy_statements": policies,
        "customer_reports": reports,
        "assumptions": assumptions,
        "missing_information": list(missing.values()),
        "conflicts": conflicts,
        "as_of": now_iso,
    }
    return EvidenceLedger.model_validate(ledger).model_dump(mode="json")


def validate_evidence_ledger(value: dict[str, Any]) -> list[str]:
    """Validate structure and provenance references before a draft is returned."""
    try:
        ledger = EvidenceLedger.model_validate(value)
    except Exception:
        return ["invalid_evidence_ledger"]
    errors: list[str] = []
    for item in [*ledger.source_facts, *ledger.policy_statements, *ledger.customer_reports, *ledger.assumptions]:
        if not item.source_ref.strip() or not item.source_system.strip():
            errors.append("evidence_missing_source_provenance")
        if item.verification == "source_record" and not item.source_ref.strip():
            errors.append("source_fact_missing_reference")
    if any(not conflict.evidence_refs for conflict in ledger.conflicts):
        errors.append("conflict_missing_evidence_refs")
    return sorted(set(errors))
