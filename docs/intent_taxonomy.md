# Ticket Intent Taxonomy

## Version and use

Taxonomy version: support-intent-v1.

The model predicts the customer's business intent. Routing outcomes and security signals are separate fields. This avoids training the intent model to treat an attack signal or missing information as a customer issue category.

## Business intents

| Intent | Meaning | Default route |
| --- | --- | --- |
| address_change | Customer asks to change or correct a delivery address | Check fulfillment state; escalate if an order mutation would be needed |
| compensation_request | Customer requests compensation, credit, or goodwill value | Deterministic eligibility check; supervisor approval required |
| damaged_item | Item or package arrived damaged or defective | Verify order facts; retrieve applicable policy; proposal only |
| delivery_delay | Delivery is late or tracking has stopped before delivery | Read delivery timeline; apply escalation rules |
| delivery_dispute | Customer disputes an attempted or completed delivery event | Compare event evidence; escalate conflicting facts |
| exchange_request | Customer requests an exchange or replacement | Retrieve item-specific policy and availability evidence |
| general_policy | Customer asks a general policy question | Policy retrieval only; cite the current applicable version |
| incorrect_item | Delivered item differs from the order | Verify ordered/delivered item evidence; retrieve policy |
| invoice_request | Customer asks for an invoice or tax document | Check approved invoice availability; do not synthesize a document |
| late_refund | Expected refund timeline appears to have passed | Read return/refund record and policy; escalate when supported |
| missing_accessory | Item arrived without an included part or accessory | Verify item/package facts; retrieve policy; escalate missing evidence |
| non_delivery | Customer says the package was not received | Compare delivery events and claim; escalate a delivered/not-received conflict |
| order_cancellation | Customer asks to cancel or check a cancellation | Check order state; no cancellation mutation in the MVP |
| order_status | Customer asks for the recorded order state | Read authorized order summary |
| partial_delivery | Only part of a multi-item or multi-package order arrived | Check each item/package and delivery event |
| payment_question | Customer asks about recorded payment status or amount | Read approved payment summary; never infer bank settlement |
| price_difference | Customer asks why the order total differs from an expectation | Explain only recorded item, discount, tax, and total fields |
| product_question | Customer asks about an item or variant in their order | Answer from the order/item record or ask for clarification |
| refund_status | Customer asks for the recorded status of a refund | Read refund record; distinguish status from eligibility |
| return_eligibility | Customer asks whether a particular item can be returned | Retrieve policy for exact marketplace, item class, and effective date |
| return_pickup | Customer asks about a return collection or pickup | Read pickup/return events; escalate missing or conflicting events |
| return_status | Customer asks about the state of an existing return | Read return record and report its timestamped status |
| loyalty_points | Customer asks about a recorded points balance or transaction | Read the synthetic rewards ledger; report recorded facts only |
| reward_expiry | Customer asks whether points are due to expire | Read expiry events; policy decisions require an approved policy and review |
| reward_redemption | Customer asks about a reward redemption | Read redemption status; eligibility or balance changes require human approval |

These three loyalty intents are supported only by synthetic local development records. The current project does not connect to a real loyalty programme, and its synthetic policy document is a draft. Missing ledger data or an eligibility question must be escalated.

### Out of scope for the current fixture

Live loyalty lookups, loyalty adjustments, reinstatements, reward issuance, refunds, and other account mutations remain unavailable. The synthetic ledger can establish only what the local fixture records; it cannot establish customer eligibility.

## Triage and security fields

- triage_status: ready, needs_clarification, unsupported, security_review, or insufficient_evidence.
- risk_flags: zero or more of instruction_override_attempt, unauthorized_record_request, sensitive_data_present, conflicting_evidence, and malformed_reference.
- intent: one business label above, or null when the business request cannot be established safely.
- confidence: model-reported score, explicitly uncalibrated in this project. Do not treat it as a probability of correctness or use it for automatic decisions.
- classifier disagreement, fallback, abstention, security signals, or unsupported intent: require human review.
- automatic routing is disabled by default. The optional consensus flag is experimental and must stay off until a production-approved labeled evaluation demonstrates acceptable selective risk.

## Legacy fixture mapping

The current expected_intent column mixes business intents with workflow signals. During data preparation:

| Existing label | v1 representation |
| --- | --- |
| Any documented business label above | Keep as intent; set triage status from the labeled expected outcome |
| ambiguous_request | intent null; triage_status needs_clarification |
| prompt_injection | intent null unless a separate business request is clear; add instruction_override_attempt; triage_status security_review |
| unauthorised_data_request | intent null; add unauthorized_record_request; triage_status security_review |

Do not silently relabel records. Preserve the original label in a provenance field and record the mapping version.

## Labeling rules

1. Label the customer's primary requested outcome, not the tool or team that will handle it.
2. If multiple intents are present, label the primary intent and place secondary labels in a separate field.
3. If the request is unclear, keep intent null and use needs_clarification.
4. If identity, authorization, or evidence is missing, do not infer intent or eligibility from an order ID alone.
5. Keep security flags separate from business intent.
6. Split training, validation, and test data by customer or order group to prevent related messages leaking across splits.
