import csv
import importlib
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from frontend import chat_context
from frontend.chat_context import (
    find_customer_for_order,
    find_latest_order_for_customer,
    resolve_conversation_context,
    resolve_customer_context,
    resolve_order_context,
    resolve_ticket_context,
)


class ChatContextTests(unittest.TestCase):
    def test_ticket_lookup_accepts_a_missing_first_letter_in_tell(self):
        self.assertEqual(resolve_ticket_context("ell me about T-045"), ("T-045", True))
        self.assertEqual(
            resolve_ticket_context("ell me about T-045 and check my refund"),
            ("T-045", False),
        )

    def test_remembers_order_for_followup(self):
        self.assertEqual(resolve_order_context('what is my order id?', '', 'ORD-ID-022d195439'), 'ORD-ID-022d195439')

    def test_new_explicit_id_replaces_inferred_context(self):
        self.assertEqual(resolve_order_context('Where is my order ORD-ID-05a6699863?', '', 'ORD-ID-022d195439'), 'ORD-ID-05a6699863')

    def test_no_order_does_not_invent_one(self):
        self.assertIsNone(resolve_order_context('tell me about this order', '', None))

    def test_multiple_ids_are_not_silently_resolved(self):
        self.assertIsNone(resolve_order_context('ORD-ID-022d195439 and ORD-ID-05a6699863', '', 'ORD-ID-022d195439'))

    def test_manual_conflict_left_for_backend_validation(self):
        self.assertEqual(resolve_order_context('ORD-ID-05a6699863', 'ORD-ID-022d195439', None), 'ORD-ID-022d195439')

    def test_customer_context_extracted_from_message(self):
        self.assertEqual(resolve_customer_context('tell me orders of CUS-0097A0C5B0', '', None), 'CUS-0097A0C5B0')

    def test_customer_context_remembers_across_followups(self):
        self.assertEqual(resolve_customer_context('What is the loyalty balance?', '', 'CUS-0097A0C5B0'), 'CUS-0097A0C5B0')

    def test_customer_context_manual_overrides_message(self):
        self.assertEqual(resolve_customer_context('Check CUS-0097A0C5B0', 'CUS-A0AB74C303', None), 'CUS-A0AB74C303')

    def test_customer_context_multiple_conflicting_returns_none(self):
        self.assertIsNone(resolve_customer_context('CUS-0097A0C5B0 and CUS-A0AB74C303', '', 'CUS-0097A0C5B0'))

    def test_unified_conversation_context(self):
        ctx = resolve_conversation_context(
            'Order ORD-ID-022d195439 for CUS-0097A0C5B0',
            previous_order_id='ORD-ID-old',
            previous_customer_id='CUS-old',
        )
        self.assertEqual(ctx['order_id'], 'ORD-ID-022d195439')
        self.assertEqual(ctx['customer_id'], 'CUS-0097A0C5B0')

    def test_autolink_order_populates_linked_customer_id(self):
        """When an order is given, its linked customer ID is automatically resolved."""
        ctx = resolve_conversation_context('Where is my order ORD-ID-9c07956d06?')
        self.assertEqual(ctx['order_id'], 'ORD-ID-9c07956d06')
        self.assertEqual(ctx['customer_id'], 'CUS-0097A0C5B0')

    def test_autolink_customer_populates_linked_order_id(self):
        """When a customer is given, their linked order ID is automatically resolved."""
        ctx = resolve_conversation_context('tell me orders of CUS-0097A0C5B0')
        self.assertEqual(ctx['customer_id'], 'CUS-0097A0C5B0')
        self.assertEqual(ctx['order_id'], 'ORD-ID-9c07956d06')

    def test_direct_mapping_lookups(self):
        self.assertEqual(find_customer_for_order('ORD-ID-9c07956d06'), 'CUS-0097A0C5B0')
        self.assertEqual(find_latest_order_for_customer('CUS-0097A0C5B0'), 'ORD-ID-9c07956d06')
        self.assertIsNone(find_customer_for_order('ORD-ID-nonexistent'))
        self.assertIsNone(find_latest_order_for_customer('CUS-NONEXISTENT'))

    def test_csv_read_failure_publishes_no_partial_orders_and_retry_finds_latest(self):
        module = importlib.reload(chat_context)
        customer_id = "CUS-1111111111"
        older_order = "ORD-ID-f000000001"
        newer_order = "ORD-ID-f000000002"

        def interrupted_read(_stream):
            yield {"order_id": older_order, "customer_id": customer_id, "order_date": "2025-04-01"}
            raise csv.Error("simulated interrupted read")

        with TemporaryDirectory() as directory:
            path = Path(directory) / "orders.csv"
            path.write_text(
                "order_id,customer_id,order_date\n"
                f"{older_order},{customer_id},2025-04-01\n"
                f"{newer_order},{customer_id},2025-05-01\n",
                encoding="utf-8",
            )
            with patch.object(module, "_ORDERS_CSV", path):
                with patch.object(module.csv, "DictReader", side_effect=interrupted_read):
                    with self.assertLogs(module.__name__, "ERROR"):
                        self.assertIsNone(module.find_latest_order_for_customer(customer_id))

                self.assertEqual(module.find_latest_order_for_customer(customer_id), newer_order)
                self.assertEqual(module.find_all_orders_for_customer(customer_id), [older_order, newer_order])

    def test_detect_customer_mismatch_blocks_explicit_foreign_customer(self):
        from frontend.chat_context import detect_customer_mismatch
        mismatch = detect_customer_mismatch("tell me orders of CUS-717541ACF6", "CUS-0097A0C5B0")
        self.assertEqual(mismatch, "CUS-717541ACF6")

    def test_detect_customer_mismatch_blocks_foreign_order_id(self):
        from frontend.chat_context import detect_customer_mismatch
        # ORD-ID-04938758d6 belongs to CUS-717541ACF6
        mismatch = detect_customer_mismatch("tell me about ORD-ID-04938758d6", "CUS-0097A0C5B0")
        self.assertEqual(mismatch, "CUS-717541ACF6")

    def test_detect_customer_mismatch_allows_own_order_id(self):
        from frontend.chat_context import detect_customer_mismatch
        # ORD-ID-9c07956d06 belongs to CUS-0097A0C5B0
        mismatch = detect_customer_mismatch("Where is my order ORD-ID-9c07956d06?", "CUS-0097A0C5B0")
        self.assertIsNone(mismatch)

    def test_detect_customer_mismatch_blocks_all_19_cross_customer_orders(self):
        from frontend.chat_context import detect_customer_mismatch
        test_pairs = [
            ("ORD-ID-00d824ff87", "CUS-7933A09A5C"),
            ("ORD-ID-01ef5a198e", "CUS-C18DFAF346"),
            ("ORD-ID-0207efc03c", "CUS-E503E35294"),
            ("ORD-ID-022d195439", "CUS-F1E507CBD1"),
            ("ORD-ID-0256dd17a2", "CUS-81DCB3318B"),
            ("ORD-ID-025fc3be0f", "CUS-9873A9BD2C"),
            ("ORD-ID-02b90efe1d", "CUS-AEAF9C98E5"),
            ("ORD-ID-03820daec5", "CUS-A470133C59"),
            ("ORD-ID-0388ee198a", "CUS-D5C2AC0B87"),
            ("ORD-ID-03978d78df", "CUS-B7F2CFF30A"),
            ("ORD-ID-0420d696ee", "CUS-1B84D151D7"),
            ("ORD-ID-0429c39d01", "CUS-7AC3C13205"),
            ("ORD-ID-042b3fe16f", "CUS-1992A406E4"),
            ("ORD-ID-048858dac0", "CUS-191C64E4D3"),
            ("ORD-ID-04938758d6", "CUS-717541ACF6"),
            ("ORD-ID-04ff46c9c9", "CUS-CDACCB4000"),
            ("ORD-ID-0559ea777f", "CUS-75E3ADF5D4"),
            ("ORD-ID-0563e1e3fc", "CUS-BC54E5FF6E"),
            ("ORD-ID-057670475c", "CUS-6A2CFA17A9"),
        ]
        base_customer = "CUS-0097A0C5B0"
        for order_id, expected_owner in test_pairs:
            mismatch = detect_customer_mismatch(f"Where is my order {order_id}?", base_customer)
            self.assertEqual(
                mismatch, expected_owner,
                f"Expected cross-customer order {order_id} to be blocked with owner {expected_owner}, got {mismatch}",
            )

    def test_active_customer_not_hijacked_by_foreign_order(self):
        # When active customer is CUS-0097A0C5B0, mentioning ORD-ID-04938758d6 does not overwrite customer
        ctx = resolve_conversation_context(
            "tell me about ORD-ID-04938758d6",
            previous_customer_id="CUS-0097A0C5B0",
            previous_order_id="ORD-ID-9c07956d06",
        )
        self.assertEqual(ctx["customer_id"], "CUS-0097A0C5B0")
        self.assertEqual(ctx["order_id"], "ORD-ID-04938758d6")
