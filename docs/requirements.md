# Day 1 Requirements and Decisions

## Goal

Build a support assistant that investigates a ticket from authorized operational records and approved policy sources, then produces a reviewable response or proposal. It must show where each material fact came from. The assistant recommends; deterministic rules validate; an authorized human approves consequential actions.

## Users and permissions

| Role | Allowed work |
| --- | --- |
| Support agent | Submit and view tickets they are allowed to handle; view scoped evidence and proposals |
| Supervisor | Review proposals, approve or reject eligible consequential proposals, and record a reason |
| Policy manager | Draft, review, publish, supersede, and retire policy versions; no customer-record access by default |
| Service operator | Inspect redacted health and audit metadata; no customer action authority by default |
| Application service | Invoke allowlisted read tools and write workflow/audit records using least-privilege credentials |

Production authentication must use an organization-approved identity provider. The provider and exact group-to-role mapping are not present in the repository and must be approved before production access is enabled.

## Functional requirements

1. Validate ticket requests and assign a server-side request ID.
2. Return one business intent, a triage status, risk flags, confidence, and classifier version.
3. Require clarification or human review for ambiguous, unsupported, low-confidence, or security-sensitive cases.
4. Query only approved read tools after caller authorization succeeds.
5. Retrieve policy passages only from approved, active, in-scope versions and include stable source references.
6. Distinguish operational facts, policy statements, assumptions, and missing information.
7. Apply deterministic rules before proposing an action.
8. Require supervisor approval for refunds, compensation, loyalty adjustments, and other consequential actions.
9. Record a safe audit trail for success, rejection, escalation, and failure without copying raw ticket text into general audit metadata.
10. Never call a live refund or compensation execution service in the MVP.

## Non-functional requirements

- Security: authenticate API callers, authorize each tool call, use least-privilege database roles, and prevent arbitrary SQL or unrestricted model tool access.
- Privacy: minimize fields, mask identifiers in model prompts and logs, and agree on retention with the data owner.
- Reliability: use bounded timeouts and retries, idempotent approval events, and controlled fallback on dependency failure.
- Traceability: retain request ID, model/classifier version, policy version, evidence references, rule result, and approval outcome.
- Change control: version and review policy and schema changes; manage database changes as migrations.
- Evaluation: use held-out ticket labels and a separate retrieval benchmark; never report training performance as generalization.
- Operations: set availability, latency, recovery, and support targets with the service owner before production launch.

## Data and environment decisions

- The current 1,000-row marketplace fixture is fictional development/evaluation data. It is not a production data source.
- The project brief lists Olist as a public historical dataset candidate. It is not present in this project and must not be joined to the fictional tickets without an explicit mapping and provenance.
- A production order source, support platform, data owner, jurisdiction, and identity provider have not been selected. Treat each as a release gate, not an implicit assumption.
- Development and CI use synthetic data. Staging must not receive production personal data unless a documented anonymization and access review is approved.
- Production order and delivery facts remain authoritative in their source systems and are accessed through narrow read-only interfaces.

## Out of scope for this MVP

- Live refunds, compensation, loyalty adjustments, address changes, cancellations, or any other mutation of an operational commerce system.
- Autonomous approval, account access, or customer identity verification by a language model.
- Using generated fixture records as actual customer or order history.
- Automatic ingestion or publication of a policy that has not passed human review.
- Production launch before a data owner, identity provider, retention policy, and operational targets are approved.

## Day 1 acceptance checklist

- [x] Supported business intents and separate routing/security signals are documented.
- [x] Dataset provenance and the production data-source gate are documented.
- [x] Policy lifecycle and retrieval metadata are documented.
- [x] Ticket, classification, evidence, tool, and audit contracts are documented.
- [x] Read/write and role boundaries are documented.
- [x] Production-oriented architecture and environment path are documented.
- [ ] Product/data owner approves production source systems and retention.
- [ ] Security owner approves identity provider and role mapping.
- [ ] Operations owner sets service-level and recovery targets.
