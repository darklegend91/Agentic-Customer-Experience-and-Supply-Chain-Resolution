import unittest
from frontend.chat_context import resolve_order_context

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
