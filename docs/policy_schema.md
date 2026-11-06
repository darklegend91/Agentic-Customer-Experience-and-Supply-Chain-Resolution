# Versioned Policy Schema

## Lifecycle

Every policy is immutable after publication. A correction creates a new version with a new content hash and a link to the superseded version. Retrieval uses only an approved version whose effective period includes the investigation's policy date.

Lifecycle values:

- draft: editable; never indexed for production retrieval.
- in_review: awaiting policy-manager approval; never indexed for production retrieval.
- approved: approved but not yet effective; deterministic decisions must not use this status.
- active: approved and effective for the declared scope.
- superseded: replaced by a later version; retained for audit and historical investigations.
- retired: no longer applicable; retained for audit and excluded from current retrieval.

The workflow may display draft and approved passages to reviewers, but a deterministic eligibility decision requires an `active` version with matching scope and dates.

## Required metadata

| Field | Type | Rule |
| --- | --- | --- |
| policy_id | string | Stable identifier across versions |
| version | string | Immutable version, for example 1.0.0 |
| status | enum | One lifecycle value above |
| title | string | Human-readable and unambiguous |
| owner | string | Accountable business policy owner |
| reviewed_by | string or null | Authorized approver; required before approved |
| created_at | timestamp | ISO 8601 UTC |
| approved_at | timestamp or null | Required before approved |
| effective_from | timestamp/date or null | Inclusive beginning of applicability; required before active |
| effective_to | timestamp/date or null | Exclusive end; null means no scheduled end |
| jurisdiction | string | Explicit legal/business scope, such as IN |
| marketplace | string | Marketplace or all only when owner approves |
| environment_scope | enum | development-only for synthetic demos; production-approved only after owner/security review |
| locale | string | Language/locale of authoritative text |
| categories | list[string] | Product or order categories in scope |
| intents | list[string] | Supported taxonomy labels |
| source_uri | string | Stable source URL or repository path |
| source_captured_at | timestamp or null | When source was captured or verified; null for original synthetic rules |
| source_sha256 | hex string or null | Hash of preserved source artifact; null only for original synthetic demo rules |
| content_sha256 | hex string or null | Hash of published policy body; required before approval |
| supersedes | policy/version reference or null | Prior version, if any |
| synthetic_demo | boolean | True for fictional project policies |

## Policy body

The body contains human-readable terms and structured rule statements. Structured fields support deterministic evaluation; prose supports citation and explanation. Do not ask a language model to convert unreviewed prose into executable eligibility rules.

Required rule sections:

- eligibility: required facts and predicates.
- exclusions: explicit cases that do not qualify.
- permitted_actions: actions that may be proposed.
- approval_required: actions or conditions requiring supervisor approval.
- escalation: missing, contradictory, or exceptional evidence routes.
- evidence_requirements: operational records needed before a conclusion.

## Example record

~~~yaml
policy_id: RETURN-ITEM-001
version: 1.0.0
status: draft
title: Item return eligibility
owner: policy-owner-placeholder
reviewed_by: null
created_at: 2026-11-02T00:00:00Z
approved_at: null
effective_from: null
effective_to: null
jurisdiction: IN
marketplace: example-marketplace
environment_scope: development-only
locale: en-IN
categories: [electronics]
intents: [return_eligibility, damaged_item]
source_uri: knowledge_base/policies/RETURN-ITEM-001/1.0.0.md
source_captured_at: null
source_sha256: null
content_sha256: null
supersedes: null
synthetic_demo: true
eligibility:
  - field: order_item.order_id
    operator: exists_and_is_authorized
  - field: order_item.category
    operator: equals
    value: electronics
exclusions: []
permitted_actions: [propose_return_review]
approval_required: [refund, compensation]
escalation:
  - when: required_evidence_missing
    route: human_review
evidence_requirements: [authorized_order_item, purchase_date, item_condition]
~~~

This example illustrates a schema, not a real marketplace policy. Replace placeholder owner/source values and obtain approval before use.

## Retrieval and citation rules

Each chunk carries policy_id, version, status, effective_from, effective_to, jurisdiction, marketplace, environment_scope, synthetic_demo, locale, category, intent, section_id, source_sha256, content_sha256, and a stable chunk_id.

Before semantic or keyword ranking, filter by approved/active status, policy date, jurisdiction, marketplace, environment scope, locale, category, and caller scope. Keep development-only synthetic records out of production collections. Return citations with policy ID, version, section/page, and source hash. Keep the source file authoritative; Milvus is a rebuildable index.
