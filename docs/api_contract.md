# Day 1 Data and Investigation Contracts

## Contract conventions

- JSON over HTTPS; FastAPI/Pydantic validates every boundary.
- Every contract has schema_version "1.0".
- Timestamps use ISO 8601 UTC.
- IDs are opaque strings; callers cannot use an identifier alone to establish authorization.
- Missing, unknown, unauthorized, and insufficient-evidence outcomes are distinct.
- Responses include stable evidence references and never claim that a proposal was executed.

## Ticket intake

| Field | Type | Requirement |
| --- | --- | --- |
| schema_version | string | Required |
| message | string | Required, bounded length, treated as untrusted text |
| locale | string | Required or safely defaulted by server |
| marketplace | string | Required if caller can operate across marketplaces |
| order_reference | string or null | Optional hint; server must authorize the resolved order |
| external_ticket_ref | string or null | Optional source-system reference; scoped and validated |

The server derives request_id, internal ticket_id, actor_id, roles, and authorized customer scope from trusted middleware and storage. Do not accept these as trusted body fields.

Example:

~~~json
{
  "schema_version": "1.0",
  "message": "The estimated delivery date passed and tracking has not changed.",
  "locale": "en-IN",
  "marketplace": "example-marketplace",
  "order_reference": "ORD-ID-example123"
}
~~~

## Classification result

Required fields: schema_version, candidate intent, triage status, risk flags, model score, classifier version, and needs_human_review. Responses also expose `classifier_provider`, `fallback_used`, `baseline_intent`, `models_agree`, `confidence_calibrated`, and `automatic_routing_enabled`. Laya and TF-IDF disagreement, fallback, abstention, or uncalibrated confidence never silently becomes an automatic decision. The current live Laya evaluation is weak; automatic routing is disabled by default.

intent is one of the documented business labels, or `other_or_unsupported`. The current classifier returns a candidate label; confidence is a model-reported value in [0, 1], not a calibrated probability. Entity extraction returns allowlisted order, item, SKU, and return references. Extracted references remain customer-reported hints and do not grant authorization.

## Evidence envelope

| Field | Meaning |
| --- | --- |
| evidence_id | Stable reference within this investigation |
| evidence_type | operational_fact or policy_statement |
| source_system | Approved source name |
| source_record_id | Opaque, access-controlled record reference |
| observed_at | Source observation time in UTC |
| policy_id, policy_version | Required for policy evidence; null for operational facts |
| section_id or page_number | Location in the cited policy source |
| content_sha256 | Hash of the source content used |
| excerpt | Bounded and redacted text, when needed for review |

The implemented evidence ledger separates source facts, retrieved policy statements and applicability, customer reports, model assumptions, missing information, and conflicts. Operational facts do not establish policy terms, and policy text does not establish a customer's order state. Workflow claims must match a deterministic source-backed claim and its narrow references exactly; unsupported or rephrased claims fail validation.

## Investigation tools

Tools are server-side allowlisted functions. Caller identity and authorization are injected by trusted middleware; the model cannot forge them.

### get_order_summary

Input: an opaque order reference plus trusted authorization context.

Output: status (found, not_found, not_authorized, insufficient_data), as_of, a bounded set of order/item fields, and evidence references. The tool is read-only and returns no unrelated customer records.

### list_delivery_events

Input: an authorized order reference.

Output: status, as_of, ordered events with source IDs/timestamps, and evidence references. Do not invent missing scans or infer delivery from an estimated date.

### get_return_refund_status

Input: an authorized order or return reference.

Output: recorded return/refund state, as_of, source reference, and explicit missing fields. Status lookup does not decide eligibility.

### get_customer_support_context

Development-only input: an authorized order reference. The tool resolves the linked customer internally and returns at most 50 loyalty transactions and 20 PII-minimized prior-contact summaries. It never returns email, phone, or customer IDs. A full result page is marked truncated; ledger inconsistencies and missing account data remain explicit. The current implementation uses synthetic fixtures only.

### search_policy

Input: bounded query, authorized marketplace, locale, and policy date.

Output: approved in-scope policy passages with policy ID/version, section/page, effective dates, content hash, and relevance score. Filter lifecycle, jurisdiction, marketplace, locale, category, and caller scope before ranking.

No tool accepts free-form SQL, arbitrary URLs, caller-selected tenant scope, or an instruction to execute a refund.

## Proposal and approval

A proposal has proposal_id, ticket_id, intent, proposed_action, reason, evidence_refs, missing_information, rule_set_version, requires_approval, and status.

Allowed statuses: draft, pending_approval, approved, rejected, escalated, closed. Approval records include reviewer identity/role, decision, reason, timestamp, and proposal version. Approval records a decision; the MVP has no action executor.

## Audit event

Record request_id, event_id, occurred_at, actor_type, actor_ref, stage, tool_name, status, error_category, latency_ms, model_version, policy_versions, evidence_refs, and approval_ref where applicable.

Do not put raw ticket text, access tokens, secrets, full addresses, or unnecessary direct identifiers in general audit metadata. Detailed evidence access is separately authorized.

## Compatibility

Additive fields may be introduced within a minor contract revision. Renames, changed meanings, or removed fields require a new major schema version and a migration plan. Preserve the version used on each stored workflow record.

## Day 4 local API and MCP surface

The local development API also provides `GET /orders/{order_id}/customer-context`, `POST /workflows` for validated message intake, and a trace endpoint that returns the typed evidence ledger. Customer-context tables require the additive local migration `002_customer_support_context.sql`. The legacy `/tickets` route and MCP tools remain fixture-only; protected workflow requests enforce caller scopes. Stored ticket lookup never exposes training/evaluation labels.

The equivalent local stdio MCP server exposes `get_ticket_details`, `classify_ticket`, `get_order_summary`, `get_order_investigation`, `list_delivery_events`, `get_return_refund_status`, `search_policy`, and `investigate_ticket`. HTTP and MCP call the same read-only tool functions. MCP read-only annotations are client-facing hints and do not replace server-side controls.

The current HTTP and MCP surfaces have no authentication or caller-to-order authorization. They are disabled outside `APP_ENV=local`, `dev`, or `development` and are intended only for the local fictional fixture. Do not expose them as production interfaces. The indexed policy corpus is synthetic draft evidence and must not be treated as approved or applicable policy.
