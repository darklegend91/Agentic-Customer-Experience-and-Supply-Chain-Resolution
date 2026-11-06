"""Checks read-only and field-minimized SQL behavior for order lookup."""

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from backend.app.order_lookup import lookup_order_readonly  # noqa: E402


class FakeCursor:
    def __init__(self):
        self.executed = []
        self.current = []

    def execute(self, query, params):
        self.executed.append((query, params))
        if "FROM orders" in query:
            self.current = [{
                "order_id": params[0], "status": "shipped", "order_date": "2026-10-01",
                "estimated_delivery": "2026-10-05", "actual_delivery": None,
                "seller_type": "marketplace", "marketplace": "Amazon.in",
            }]
        elif "FROM order_items" in query:
            self.current = [{"item_id": "ITEM-1", "product_name": "Fixture item", "unit_price_inr": "100.00"}]
        elif "FROM delivery_events" in query:
            self.current = [{"event_id": "EVENT-1", "event_type": "shipped", "event_time": "2026-10-02T10:00:00+00:00"}]
        else:
            self.current = []

    def fetchone(self):
        return self.current[0] if self.current else None

    def fetchall(self):
        return self.current

    def close(self):
        pass


class OrderLookupTests(unittest.TestCase):
    def test_lookup_is_read_only_parameterized_and_minimized(self):
        fake_cursor = FakeCursor()
        fake_connection = Mock()
        fake_connection.cursor.return_value = fake_cursor
        with patch.dict(os.environ, {"APP_ENV": "local", "DATABASE_URL": "postgresql://test"}, clear=False):
            with patch("backend.app.order_lookup.psycopg2.connect", return_value=fake_connection) as connect:
                result = lookup_order_readonly("ORD-ID-test000001")

        connect.assert_called_once()
        fake_connection.set_session.assert_called_once_with(readonly=True, autocommit=False)
        self.assertEqual(len(fake_cursor.executed), 4)
        self.assertTrue(all(params == ("ORD-ID-test000001",) for _, params in fake_cursor.executed))
        selected_sql = " ".join(query for query, _ in fake_cursor.executed).lower()
        self.assertNotIn("customer_id", selected_sql)
        self.assertNotIn("return_eligibility", selected_sql)
        self.assertEqual(result["order"]["order_id"], "ORD-ID-test000001")
        self.assertEqual(len(result["items"]), 1)
        self.assertEqual(fake_connection.rollback.call_count, 1)
        fake_connection.close.assert_called_once()

    def test_lookup_refuses_non_development_environment(self):
        with patch.dict(os.environ, {"APP_ENV": "production", "DATABASE_URL": "postgresql://test"}, clear=False):
            with self.assertRaisesRegex(RuntimeError, "disabled outside local development"):
                lookup_order_readonly("ORD-ID-test000001")


if __name__ == "__main__":
    unittest.main()
