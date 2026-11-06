"""Checks Day 4 repository queries are bounded, parameterized, and read-only."""

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from backend.app.db.repositories import get_order_summary_readonly, get_ticket_readonly  # noqa: E402


class FakeCursor:
    def __init__(self):
        self.executed = []
        self.current = []

    def execute(self, query, params):
        self.executed.append((query, params))
        if "FROM orders" in query:
            self.current = [{
                "order_id": params[0], "status": "shipped", "marketplace": "Amazon.in",
                "order_date": "2026-10-01",
            }]
        elif "FROM order_items" in query:
            self.current = [{"item_id": "ITEM-1", "product_name": "Fixture product", "quantity": 1}]
        elif "FROM tickets" in query:
            self.current = [{"ticket_id": params[0], "message": "My item is damaged", "order_id": "ORD-ID-1"}]
        else:
            self.current = []

    def fetchone(self):
        return self.current[0] if self.current else None

    def fetchall(self):
        return self.current

    def close(self):
        pass


class Day4RepositoryTests(unittest.TestCase):
    def setUp(self):
        self.cursor = FakeCursor()
        self.connection = Mock()
        self.connection.cursor.return_value = self.cursor

    def _connect(self):
        return patch(
            "backend.app.db.session.psycopg2.connect",
            return_value=self.connection,
        )

    def test_order_summary_uses_allowlisted_columns_and_read_only_session(self):
        with patch.dict(os.environ, {"APP_ENV": "local", "DATABASE_URL": "postgresql://fixture"}, clear=False):
            with self._connect() as connect:
                result = get_order_summary_readonly("ORD-ID-test000001")

        connect.assert_called_once()
        self.connection.set_session.assert_called_once_with(readonly=True, autocommit=False)
        self.assertEqual(len(self.cursor.executed), 3)
        self.assertEqual(self.cursor.executed[0], ("SELECT set_config('statement_timeout', %s, true)", ("5000ms",)))
        self.assertTrue(all(params == ("ORD-ID-test000001",) for _, params in self.cursor.executed[1:]))
        sql = " ".join(query for query, _ in self.cursor.executed).lower()
        self.assertNotIn("customer_id", sql)
        self.assertNotIn("expected_intent", sql)
        self.assertNotIn("expected_handling", sql)
        self.assertEqual(result["order"]["order_id"], "ORD-ID-test000001")
        self.assertEqual(result["items"][0]["item_id"], "ITEM-1")
        self.connection.rollback.assert_called_once()
        self.connection.close.assert_called_once()

    def test_ticket_query_does_not_select_evaluation_labels(self):
        with patch.dict(os.environ, {"APP_ENV": "local", "DATABASE_URL": "postgresql://fixture"}, clear=False):
            with self._connect() as connect:
                result = get_ticket_readonly("T-003")

        query, params = self.cursor.executed[1]
        self.assertEqual(params, ("T-003",))
        self.assertIn("select ticket_id, message, order_id", query.lower())
        self.assertNotIn("expected_intent", query.lower())
        self.assertNotIn("expected_handling", query.lower())
        self.assertEqual(result["ticket_id"], "T-003")
        self.assertNotIn("customer_id", result)


if __name__ == "__main__":
    unittest.main()
