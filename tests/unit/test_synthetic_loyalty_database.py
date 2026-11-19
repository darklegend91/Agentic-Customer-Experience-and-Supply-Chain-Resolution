"""Comprehensive test suite for synthetic loyalty database matching customer and order IDs.

Validates against specifications in docs/Project_5.docx:
- Section 4.5: Synthetic policy knowledge base (loyalty accrual, missing points, expiry, redemption).
- Section 4.6: Data integration rules (explicit ticket-to-order mapping, no orphan records).
- Section 9.1: Propose loyalty correction only when transaction/points rules are verified.
- Section 10.1: get_reward_ledger / customer context read-only retrieval without live mutations.
"""

from __future__ import annotations

import csv
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]
PROCESSED = ROOT / "data" / "processed"
SYNTHETIC = ROOT / "data" / "synthetic"


class SyntheticLoyaltyDatabaseIntegrityTests(unittest.TestCase):
    """Verify CSV datasets and database fixture alignment."""

    @classmethod
    def setUpClass(cls):
        # Load orders
        with open(PROCESSED / "clean_orders.csv", newline="", encoding="utf-8-sig") as f:
            cls.orders = {row["order_id"]: row for row in csv.DictReader(f)}

        # Customers are derived directly from the canonical orders dataset
        cls.customers = {row["customer_id"]: row for row in cls.orders.values()}

        # Load synthetic customer loyalty accounts
        with open(SYNTHETIC / "customer_loyalty_accounts.csv", newline="", encoding="utf-8-sig") as f:
            cls.accounts = list(csv.DictReader(f))

        # Load synthetic loyalty transactions
        with open(SYNTHETIC / "loyalty_transactions.csv", newline="", encoding="utf-8-sig") as f:
            cls.transactions = list(csv.DictReader(f))

        # Load synthetic customer communications
        with open(SYNTHETIC / "customer_communications.csv", newline="", encoding="utf-8-sig") as f:
            cls.communications = list(csv.DictReader(f))

        # Load support context tickets
        with open(SYNTHETIC / "support_context_tickets.csv", newline="", encoding="utf-8-sig") as f:
            cls.support_tickets = list(csv.DictReader(f))

        # Load ticket order mappings
        with open(SYNTHETIC / "ticket_order_mapping.csv", newline="", encoding="utf-8-sig") as f:
            cls.ticket_mappings = list(csv.DictReader(f))

    def test_customer_loyalty_accounts_match_customers_1_to_1(self):
        """Every customer must have exactly one loyalty account (1,000 fixtures)."""
        self.assertEqual(len(self.accounts), 1000)
        account_cust_ids = [row["customer_id"] for row in self.accounts]
        self.assertEqual(len(set(account_cust_ids)), 1000)

        for cust_id in account_cust_ids:
            self.assertIn(
                cust_id,
                self.customers,
                f"Loyalty account references non-existent customer: {cust_id}",
            )

    def test_loyalty_account_tiers_and_balance_bounds(self):
        """Accounts must have valid tiers, positive balances, and valid statuses."""
        valid_tiers = {"standard", "plus", "premium"}
        valid_statuses = {"active", "suspended", "closed"}

        for row in self.accounts:
            self.assertTrue(row["account_id"].startswith("LOY-"))
            self.assertIn(row["loyalty_tier"], valid_tiers)
            self.assertIn(row["account_status"], valid_statuses)
            balance = int(row["points_balance"])
            self.assertGreaterEqual(balance, 0)

    def test_loyalty_transactions_reference_valid_customers_and_orders(self):
        """Every transaction must reference an existing customer and (if set) a valid order."""
        valid_event_types = {
            "points_earned", "reward_redeemed", "points_expired", "points_adjusted",
        }
        valid_statuses = {"posted", "pending", "reversed"}

        for tx in self.transactions:
            self.assertTrue(tx["event_id"].startswith("LTX-"))
            self.assertIn(
                tx["customer_id"],
                self.customers,
                f"Transaction references missing customer: {tx['customer_id']}",
            )
            order_id = tx.get("order_id")
            if order_id:
                self.assertIn(
                    order_id,
                    self.orders,
                    f"Transaction references missing order: {order_id}",
                )
            self.assertIn(tx["event_type"], valid_event_types)
            self.assertIn(tx["status"], valid_statuses)

    def test_mathematical_loyalty_balance_reconciliation(self):
        """Account points balance must equal the sum of posted transaction deltas."""
        ledger_sums: dict[str, int] = {}
        for tx in self.transactions:
            if tx.get("status") == "posted":
                cid = tx["customer_id"]
                delta = int(tx["points_delta"])
                ledger_sums[cid] = ledger_sums.get(cid, 0) + delta

        mismatches = []
        for acc in self.accounts:
            cid = acc["customer_id"]
            balance = int(acc["points_balance"])
            expected = ledger_sums.get(cid, 0)
            if balance != expected:
                mismatches.append((cid, balance, expected))

        self.assertEqual(
            mismatches,
            [],
            f"Mismatched balances detected: {mismatches[:5]}",
        )

    def test_support_context_tickets_map_to_valid_orders(self):
        """Project_5 Section 4.6: all synthetic tickets must map to verifiable orders."""
        self.assertEqual(len(self.support_tickets), 180)
        for ticket in self.support_tickets:
            order_id = ticket["order_id"]
            self.assertIn(
                order_id,
                self.orders,
                f"Synthetic support ticket {ticket['ticket_id']} has unmapped order {order_id}",
            )

    def test_customer_communications_reference_valid_customers_and_orders(self):
        """All communications must link to valid customers and orders."""
        for comm in self.communications:
            self.assertTrue(comm["communication_id"].startswith("COM-"))
            self.assertIn(comm["customer_id"], self.customers)
            order_id = comm.get("order_id")
            if order_id:
                self.assertIn(order_id, self.orders)

    def test_reversed_transactions_trigger_simulation_proposals(self):
        """Project_5 Section 9.1 & 10.1: Only provable reversed transactions yield proposals."""
        from backend.app.domain.reward_rules import assess_reward_request

        # Find an actual transaction from synthetic set with reversed status, or construct a provable fixture
        reversed_tx = next((tx for tx in self.transactions if tx["status"] == "reversed"), None)
        if reversed_tx is None:
            reversed_tx = {
                "event_id": "LTX-TEST-REV",
                "customer_id": "CUS-8516C1E29C",
                "order_id": "ORD-ID-adb5bc6dc0",
                "event_type": "points_earned",
                "points_delta": 50,
                "status": "reversed",
            }
        
        test_state = {
            "order_id": reversed_tx["order_id"],
            "message": "My points for this order were reversed, please reinstate them.",
            "classification": {"intent": "loyalty_points"},
            "evidence": {
                "order": {
                    "status": "found",
                    "order_id": reversed_tx["order_id"],
                    "order": {"order_id": reversed_tx["order_id"], "status": "delivered"},
                },
                "customer_context": {
                    "status": "found",
                    "loyalty_account": {"account_id": "LOY-TEST", "points_balance": 100},
                    "loyalty_transactions": [{
                        "event_id": reversed_tx["event_id"],
                        "order_id": reversed_tx["order_id"],
                        "event_type": "points_earned",
                        "points_delta": int(reversed_tx["points_delta"]),
                        "status": "reversed",
                    }],
                    "missing_fields": [],
                    "conflicts": [],
                },
            },
        }
        res = assess_reward_request(
            test_state,
            applicable_policy_hits=[{"policy_id": "DEMO-LOYALTY-LEDGER", "policy_version": "1.0.0"}],
        )
        self.assertEqual(res["outcome"], "proposal")
        self.assertTrue(res["requires_approval"])
        self.assertEqual(res["proposal"]["action_kind"], "loyalty_reinstatement_review_simulation")
        self.assertEqual(res["proposal"]["adjustment_draft"]["points_delta"], int(reversed_tx["points_delta"]))

    def test_read_only_balance_inquiry_does_not_require_approval(self):
        """Project_5 Section 10.1: Read-only reward balance requires no proposal or approval."""
        from backend.app.domain.reward_rules import assess_reward_request

        test_state = {
            "order_id": "ORD-ID-adb5bc6dc0",
            "message": "How many loyalty points do I have currently?",
            "classification": {"intent": "loyalty_points"},
            "evidence": {
                "order": {"status": "found", "order_id": "ORD-ID-adb5bc6dc0"},
                "customer_context": {
                    "status": "found",
                    "loyalty_account": {"account_id": "LOY-TEST", "points_balance": 60},
                    "loyalty_transactions": [],
                    "missing_fields": [],
                    "conflicts": [],
                },
            },
        }
        res = assess_reward_request(test_state)
        self.assertEqual(res["outcome"], "answer")
        self.assertFalse(res.get("requires_approval", False))
        self.assertIsNone(res.get("proposal"))


if __name__ == "__main__":
    unittest.main()
