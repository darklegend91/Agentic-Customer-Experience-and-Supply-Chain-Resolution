# Loyalty system guide

## What is available now

The loyalty workflow is evidence-first and safe by default. It can:

- answer read-only points, expiry, and redemption questions from the authorized ledger;
- create a **simulation-only** reinstatement proposal only when the policy is active and applicable, the order is delivered, and the ledger contains an exact positive `points_earned` event for that order with status `reversed`;
- pause the workflow for a second reviewer; and
- show non-sensitive provider readiness in the Streamlit Data explorer.

It will not estimate a missing-points amount, credit points automatically, or treat a customer message as proof. Missing data, a non-delivered order, a truncated ledger, a balance conflict, or a draft/inapplicable policy all route to human review.

## Using the application

1. Start the FastAPI service and Streamlit UI with the project’s normal local commands.
2. In **Investigation workbench**, enter the authorized order ID and ask a loyalty question.
   - Read-only example: `How many points are recorded for order ORD-ID-...?`
   - Reinstatement-review example: `The points for order ORD-ID-... were reversed. Please reinstate them.`
3. Open **Evidence & decision data** to inspect the order, loyalty events, policy citations, and deterministic rule outcome.
4. If every requirement is verified, the UI displays a **Verified loyalty adjustment draft**. Its amount is calculated only from recorded reversed earning events.
5. A reviewer with the separate reviewer token can approve or reject the proposal. Approval is a simulation record only; no balance changes.

The bundled fixture does not include reversed earning events or an active production policy, so ordinary local demo requests correctly escalate instead of producing a proposal. The automated tests exercise the proposal path with isolated verified evidence.

## Publishing a real policy

Use [the production policy template](loyalty-production-policy-template.md) as the starting point. This application cannot approve policy on behalf of your organization.

1. Replace every `REPLACE_WITH...` value with the approved source, owner, reviewer, hashes, marketplace, and dates.
2. Have the policy owner and authorized reviewer approve the immutable final version.
3. Change its lifecycle to `active` only after approval and once `effective_from` is reached.
4. Publish it to a production-only policy collection. Do not place it in the development synthetic collection or reuse the development `DEMO-LOYALTY-LEDGER` policy.
5. Validate retrieval: the policy must be `active`, non-synthetic, production-scoped, locale/jurisdiction/marketplace matched, and cited by the evidence ledger. Otherwise the workflow must keep escalating.

## Provider readiness and safe simulation

The UI’s **Data explorer** includes **Inspect loyalty provider readiness**. It only returns mode, readiness, and validation errors; it never exposes an endpoint or secret.

The safe default is:

```dotenv
LOYALTY_PROVIDER_MODE=disabled
```

For a no-write local wiring check, set:

```dotenv
APP_ENV=local
LOYALTY_PROVIDER_MODE=simulation
```

Simulation returns an acknowledgement only; it does not change a database or an external rewards account.

`http_json` is a restricted adapter for a future reviewed integration. It requires `APP_ENV=production`, an HTTPS endpoint, a secret-manager supplied token, and a comma-separated exact allowlist in `LOYALTY_PROVIDER_ALLOWED_HOSTS`. It rejects local/private destinations unless an operator explicitly permits one. Its JSON contract is:

```json
{
  "adjustment_id": "idempotency-key",
  "account_id": "opaque account ID",
  "order_id": "authorized order ID",
  "points_delta": 25,
  "reason_code": "reinstate_reversed_points"
}
```

The provider must honor `Idempotency-Key` and return `provider_reference` plus the identical `applied_points_delta`.

There is intentionally no live-execution route yet. Before adding one, deploy a production-capable workflow/audit store, retain a durable execution receipt, add a second-person execution authorization, review the provider-specific contract, and perform staging tests. This prevents an approval click from silently becoming an external money-like action.

## Test the feature

Run the focused loyalty tests:

```bash
.venv-multi/bin/python -m unittest tests.unit.test_loyalty_workflow -v
```

Then run the full suite:

```bash
.venv-multi/bin/python -m unittest discover -s tests -p 'test*.py' -v
```

The focused tests cover normal read-only answers, refusal when an amount cannot be proven, verified simulation proposal creation, policy absence, and provider configuration safeguards.
