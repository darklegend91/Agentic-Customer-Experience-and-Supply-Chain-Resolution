import unittest
from unittest.mock import Mock, call, patch

import psycopg2

from backend.app.db import repositories, session


ORDER_ID = "ORD-ID-test000001"


class NeonReadOnlyRetryTests(unittest.TestCase):
    def setUp(self):
        self.pool = Mock()
        self.enterContext(patch.object(session, "require_local_development"))
        self.enterContext(patch.dict(session.os.environ, {"DATABASE_URL": "postgresql://fixture"}))
        self.enterContext(patch.object(session, "_get_readonly_pool", return_value=self.pool))

    def test_order_investigation_replaces_a_closed_connection(self):
        closed = Mock(closed=1)
        closed.rollback.side_effect = psycopg2.InterfaceError("connection already closed")
        fresh = Mock(closed=0)
        fresh.cursor.return_value.fetchone.return_value = {
            "order_record": {"order_id": ORDER_ID, "status": "processing"},
            "items": [],
            "delivery_events": [],
            "returns_refunds": [],
        }
        self.pool.getconn.side_effect = [closed, fresh]

        result = repositories.get_order_investigation_readonly(ORDER_ID)

        self.assertEqual(result["order"]["status"], "processing")
        self.assertEqual(self.pool.putconn.call_args_list, [call(closed, close=True), call(fresh, close=False)])
        closed.rollback.assert_called_once()
        fresh.set_session.assert_called_once_with(readonly=True, autocommit=False)

    def test_order_summary_replays_the_read_after_a_disconnect_mid_query(self):
        dropped = Mock(closed=0)
        dropped_cursor = dropped.cursor.return_value
        dropped_cursor.fetchone.return_value = {"order_id": ORDER_ID, "status": "pending"}
        dropped_cursor.execute.side_effect = [None, psycopg2.OperationalError("server closed the connection")]
        fresh = Mock(closed=0)
        fresh_cursor = fresh.cursor.return_value
        fresh_cursor.fetchone.return_value = {"order_id": ORDER_ID, "status": "processing"}
        fresh_cursor.fetchall.return_value = [{"item_id": "ITEM-1"}]
        self.pool.getconn.side_effect = [dropped, fresh]

        result = repositories.get_order_summary_readonly(ORDER_ID)

        self.assertEqual(result["order"]["status"], "processing")
        self.assertEqual(result["items"], [{"item_id": "ITEM-1"}])
        self.assertEqual(fresh_cursor.execute.call_args_list, dropped_cursor.execute.call_args_list)
        dropped_cursor.close.assert_called_once()
        self.assertEqual(self.pool.putconn.call_args_list, [call(dropped, close=True), call(fresh, close=False)])

    def test_order_read_retries_only_connection_errors_and_only_once(self):
        for error, attempts in [(psycopg2.InterfaceError, 2), (psycopg2.ProgrammingError, 1)]:
            with self.subTest(error=error):
                self.pool.reset_mock()
                connections = [Mock(closed=0) for _ in range(2)]
                for connection in connections:
                    connection.cursor.return_value.execute.side_effect = error("read failed")
                self.pool.getconn.side_effect = connections

                with self.assertRaises(session.DatabaseUnavailable) as raised:
                    repositories.get_order_investigation_readonly(ORDER_ID)

                self.assertIsInstance(raised.exception.__cause__, error)
                self.assertEqual(self.pool.getconn.call_count, attempts)
                self.assertEqual(
                    self.pool.putconn.call_args_list,
                    [call(connection, close=True) for connection in connections[:attempts]],
                )

    def test_ticket_report_and_chat_context_reads_recover_from_a_dropped_connection(self):
        ticket = {"ticket_id": "T-100", "order_id": ORDER_ID, "message": "Check this ticket"}
        anchor = {"ticket_id": "T-100", "order_id": ORDER_ID, "customer_id": "CUS-0844BCE290"}
        related = {"orders": [{"order_id": ORDER_ID}], "tickets": [{"ticket_id": "T-100", "order_id": ORDER_ID}]}
        lookups = (
            (lambda: repositories.get_ticket_readonly("T-100"), ticket),
            (lambda: repositories.get_chat_anchor_readonly(ticket_id="T-100", order_id=None, customer_id=None), anchor),
            (lambda: repositories.get_chat_relationships_readonly(
                order_id=ORDER_ID, customer_id=anchor["customer_id"],
                allowed_order_ids=frozenset({"*"}), allowed_ticket_ids=frozenset({"*"}),
            ), related),
        )
        for read, expected in lookups:
            with self.subTest(fields=sorted(expected)):
                self.pool.reset_mock()
                dropped = Mock(closed=0)
                dropped.cursor.return_value.execute.side_effect = psycopg2.OperationalError("server closed the connection")
                fresh = Mock(closed=0)
                fresh.cursor.return_value.fetchone.return_value = expected
                self.pool.getconn.side_effect = [dropped, fresh]

                self.assertEqual(read(), expected)
                self.assertEqual(self.pool.putconn.call_args_list, [call(dropped, close=True), call(fresh, close=False)])
