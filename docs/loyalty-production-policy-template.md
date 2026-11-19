---
policy_id: LOYALTY-CORRECTION-REINSTATEMENT
version: 1.0.0
status: in_review
title: Loyalty points reinstatement for verified reversed earnings
owner: REPLACE_WITH_ACCOUNTABLE_POLICY_OWNER
reviewed_by: null
created_at: REPLACE_WITH_ISO_8601_UTC_TIMESTAMP
approved_at: null
effective_from: null
effective_to: null
jurisdiction: IN
marketplace: REPLACE_WITH_MARKETPLACE
environment_scope: production
locale: en-IN
categories: [all]
intents: [loyalty_points]
source_uri: REPLACE_WITH_IMMUTABLE_POLICY_SOURCE
source_captured_at: REPLACE_WITH_ISO_8601_UTC_TIMESTAMP
source_sha256: REPLACE_WITH_SOURCE_SHA256
content_sha256: REPLACE_WITH_PUBLISHED_CONTENT_SHA256
supersedes: null
synthetic_demo: false
eligibility:
  - field: order.status
    operator: equals
    value: delivered
  - field: loyalty_transaction.event_type
    operator: equals
    value: points_earned
  - field: loyalty_transaction.status
    operator: equals
    value: reversed
  - field: loyalty_transaction.order_id
    operator: equals_authorized_order
exclusions:
  - unverified_customer_report
  - missing_or_truncated_ledger
  - inconsistent_ledger_balance
permitted_actions: [propose_loyalty_reinstatement_review]
approval_required: [loyalty_points_reinstatement]
escalation:
  - when: evidence_missing_or_conflicting
    route: human_review
  - when: requested_amount_is_not_exactly_a_recorded_reversed_earning
    route: human_review
evidence_requirements:
  - authorized_order
  - delivered_order_status
  - active_applicable_policy
  - complete_loyalty_account_snapshot
  - exact_reversed_points_earned_transaction
---

# Loyalty points reinstatement policy template

This is a publication template, not an approved policy. Do not change its
status to `active` until the named policy owner and the authorized reviewer
have approved the final content, hashes, scope, and effective dates.

## Rule

The service may create a **simulation-only** review proposal when all listed
evidence requirements are met. The proposed number of points must equal the
sum of the positive, recorded `points_earned` transactions for the authorized
order whose status is `reversed`. It must not estimate points from an order
total, customer tier, or the customer's message.

## Non-actions

Approval of a proposal records a review outcome only. It does not alter a
loyalty balance, issue a reward, contact a customer, or call a provider.
External execution needs a separately reviewed, auditable release and
provider-specific contract.
