"""Focused safety tests for loyalty evidence, review proposals, and provider config."""

from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from backend.app.domain.reward_rules import assess_reward_request
from backend.app.loyalty.provider import LoyaltyProviderError, apply_adjustment, provider_status
from backend.app.approval.workflow_state import evidence_fingerprint


ORDER_ID = "ORD-ID-Loyalty123"
ACCOUNT_ID = "LOYALTY-ACCOUNT-1"


def reward_state(*, message: str, events: list[dict] | None = None) -> dict:
    return {
        "order_id": ORDER_ID,
        "message": message,
        "classification": {"intent": "loyalty_points"},
        "evidence": {
            "order": {
                "status": "found",
                "order_id": ORDER_ID,
                "order": {"order_id": ORDER_ID, "status": "delivered"},
                "evidence_refs": {"order": [f"order:{ORDER_ID}"]},
            },
            "customer_context": {
                "status": "found",
                "loyalty_account": {"account_id": ACCOUNT_ID, "points_balance": 40},
                "loyalty_transactions": events or [],
                "missing_fields": [],
                "conflicts": [],
                "evidence_refs": {
                    "loyalty_account": [f"loyalty_account:{ACCOUNT_ID}"],
                    "loyalty_transactions": ["loyalty_transaction:LTX-1"],
                },
            },
        },
    }


ACTIVE_POLICY = [{"policy_id": "LOYALTY-CORRECTION", "policy_version": "1.0.0"}]
REVERSED_EVENT = {
    "event_id": "LTX-1",
    "order_id": ORDER_ID,
    "event_type": "points_earned",
    "points_delta": 42,
    "status": "reversed",
}


class LoyaltyRewardRulesTests(unittest.TestCase):
    def test_evidence_fingerprint_changes_when_a_loyalty_event_changes(self):
        evidence = reward_state(message="My points were reversed.", events=[REVERSED_EVENT])["evidence"]
        original = evidence_fingerprint(evidence)
        changed = reward_state(message="My points were reversed.", events=[{**REVERSED_EVENT, "status": "posted"}])["evidence"]
        self.assertNotEqual(original, evidence_fingerprint(changed))

    def test_read_only_balance_uses_recorded_facts_without_a_proposal(self):
        result = assess_reward_request(
            reward_state(message="How many loyalty points do I have?"),
        )
        self.assertEqual(result["outcome"], "answer")
        self.assertEqual(result["reason_codes"], ["read_only_reward_balance_available"])
        self.assertIsNone(result["proposal"])

    def test_exact_reversed_earning_creates_a_simulation_review_proposal(self):
        result = assess_reward_request(
            reward_state(
                message="My points were reversed. Please reinstate the points for this order.",
                events=[REVERSED_EVENT],
            ),
            applicable_policy_hits=ACTIVE_POLICY,
        )
        self.assertEqual(result["outcome"], "proposal")
        self.assertTrue(result["requires_approval"])
        proposal = result["proposal"]
        self.assertEqual(proposal["action_kind"], "loyalty_reinstatement_review_simulation")
        self.assertEqual(proposal["permitted_options"], ["approve_simulation", "reject"])
        self.assertEqual(proposal["adjustment_draft"]["points_delta"], 42)
        self.assertEqual(proposal["adjustment_draft"]["source_event_ids"], ["LTX-1"])
        self.assertEqual(proposal["policy_versions"], ["LOYALTY-CORRECTION@1.0.0"])

    def test_missing_points_without_an_exact_reversed_ledger_event_escalates(self):
        result = assess_reward_request(
            reward_state(message="The points for this order are missing."),
            applicable_policy_hits=ACTIVE_POLICY,
        )
        self.assertEqual(result["outcome"], "needs_information")
        self.assertEqual(result["reason_codes"], ["reward_correction_amount_not_provable_from_ledger"])
        self.assertIn("reversed_points_earned_transaction", result["missing_information"])

    def test_reinstatement_needs_an_active_policy_even_with_exact_ledger_evidence(self):
        result = assess_reward_request(
            reward_state(
                message="Please reinstate the reversed points.", events=[REVERSED_EVENT],
            ),
        )
        self.assertEqual(result["outcome"], "escalate")
        self.assertEqual(result["reason_codes"], ["reward_action_requires_approved_rule_and_human_review"])


class LoyaltyProviderTests(unittest.TestCase):
    def test_simulation_provider_never_performs_an_external_write(self):
        with patch.dict(os.environ, {"APP_ENV": "local", "LOYALTY_PROVIDER_MODE": "simulation"}, clear=False):
            status = provider_status()
            result = apply_adjustment(
                adjustment={
                    "account_id": ACCOUNT_ID,
                    "order_id": ORDER_ID,
                    "points_delta": 42,
                    "reason_code": "reinstate_reversed_points",
                },
                idempotency_key="loyalty-test-key",
            )
        self.assertTrue(status["configured"])
        self.assertFalse(status["external_writes_enabled"])
        self.assertEqual(result["status"], "simulated")
        self.assertEqual(result["applied_points_delta"], 42)

    def test_http_provider_rejects_an_insecure_or_local_destination(self):
        with patch.dict(os.environ, {
            "APP_ENV": "production",
            "LOYALTY_PROVIDER_MODE": "http_json",
            "LOYALTY_PROVIDER_URL": "http://localhost:9999/adjustments",
            "LOYALTY_PROVIDER_TOKEN": "not-a-real-token",
            "LOYALTY_ALLOW_PRIVATE_PROVIDER_HOST": "false",
        }, clear=False):
            status = provider_status()
        self.assertFalse(status["configured"])
        self.assertIn("HTTPS", " ".join(status["errors"]))

    def test_http_provider_requires_an_explicit_exact_host_allowlist(self):
        with patch.dict(os.environ, {
            "APP_ENV": "production",
            "LOYALTY_PROVIDER_MODE": "http_json",
            "LOYALTY_PROVIDER_URL": "https://rewards.example.test/adjustments",
            "LOYALTY_PROVIDER_TOKEN": "not-a-real-token",
            "LOYALTY_PROVIDER_ALLOWED_HOSTS": "other.example.test",
        }, clear=False):
            status = provider_status()
        self.assertFalse(status["configured"])
        self.assertIn("allowed", " ".join(status["errors"]).lower())

    def test_disabled_provider_fails_closed(self):
        with patch.dict(os.environ, {"APP_ENV": "local", "LOYALTY_PROVIDER_MODE": "disabled"}, clear=False):
            with self.assertRaises(LoyaltyProviderError):
                apply_adjustment(
                    adjustment={
                        "account_id": ACCOUNT_ID,
                        "order_id": ORDER_ID,
                        "points_delta": 42,
                        "reason_code": "reinstate_reversed_points",
                    },
                    idempotency_key="loyalty-test-key",
                )


if __name__ == "__main__":
    unittest.main()
