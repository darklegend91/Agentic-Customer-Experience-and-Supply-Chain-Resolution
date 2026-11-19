import unittest
from frontend.chat_context import (
    find_customer_for_order,
    find_latest_order_for_customer,
    resolve_conversation_context,
    resolve_customer_context,
    resolve_order_context,
)


class ChatContextTests(unittest.TestCase):
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
