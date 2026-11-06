"""Quality checks for the generated fictional marketplace fixture."""

import csv
import re
import unittest
from datetime import date, datetime
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA = PROJECT_ROOT / "data" / "raw"
PDF_OUTPUT = PROJECT_ROOT / "output" / "pdf"


def read_rows(name):
    with (DATA / name).open(newline="", encoding="utf-8-sig") as stream:
        return list(csv.DictReader(stream))


class FixtureQualityTests(unittest.TestCase):
    def test_core_tables_have_one_thousand_records(self):
        self.assertEqual(len(read_rows("customers.csv")), 1000)
        self.assertEqual(len(read_rows("orders.csv")), 1000)
        self.assertEqual(len(read_rows("tickets.csv")), 1000)

    def test_ids_are_unique_and_order_ids_match_format(self):
        for filename, key in (("customers.csv", "customer_id"), ("orders.csv", "order_id"), ("tickets.csv", "ticket_id")):
            values = [row[key] for row in read_rows(filename)]
            self.assertEqual(len(values), len(set(values)), filename)
        self.assertTrue(all(re.fullmatch(r"ORD-ID-[a-z0-9]{10}", row["order_id"]) for row in read_rows("orders.csv")))

    def test_account_creation_precedes_orders_and_returns_follow_delivery(self):
        customers = {row["customer_id"]: row for row in read_rows("customers.csv")}
        orders = {row["order_id"]: row for row in read_rows("orders.csv")}
        for o in orders.values():
            c = customers[o["customer_id"]]
            self.assertLessEqual(date.fromisoformat(c["account_created_date"]), date.fromisoformat(o["order_date"]))
        for r in read_rows("returns_refunds.csv"):
            o = orders[r["order_id"]]
            req_date = datetime.fromisoformat(r["requested_at"]).date()
            if o["actual_delivery"]:
                self.assertGreaterEqual(req_date, date.fromisoformat(o["actual_delivery"]))
            else:
                self.assertGreaterEqual(req_date, date.fromisoformat(o["order_date"]))

    def test_relationships_and_evaluation_cases_resolve(self):
        customers = {row["customer_id"] for row in read_rows("customers.csv")}
        orders = read_rows("orders.csv")
        order_ids = {row["order_id"] for row in orders}
        ticket_rows = read_rows("tickets.csv")
        ticket_ids = {row["ticket_id"] for row in ticket_rows}
        self.assertTrue(all(row["customer_id"] in customers for row in orders))
        self.assertTrue(all(not row["order_id"] or row["order_id"] in order_ids for row in ticket_rows))
        self.assertTrue(all(row["ticket_id"] in ticket_ids for row in read_rows("evaluation_cases.csv")))

    def test_data_has_meaningful_product_intent_and_language_variety(self):
        items = read_rows("order_items.csv")
        tickets = read_rows("tickets.csv")
        self.assertGreaterEqual(len({row["category"] for row in items}), 12)
        self.assertGreaterEqual(len({row["expected_intent"] for row in tickets}), 12)
        self.assertGreaterEqual(len({row["message"] for row in tickets}), 950)

    def test_no_csv_filename_or_content_contains_synthetic(self):
        for path in DATA.glob("*.csv"):
            self.assertNotIn("synthetic", path.name.lower())
            self.assertNotIn("synthetic", path.read_text(encoding="utf-8-sig").lower())

    def test_delivery_events_follow_order_dates_and_prices_are_positive(self):
        orders = {row["order_id"]: row for row in read_rows("orders.csv")}
        for event in read_rows("delivery_events.csv"):
            order = orders[event["order_id"]]
            event_day = datetime.fromisoformat(event["event_time"]).date()
            self.assertGreaterEqual(event_day, date.fromisoformat(order["order_date"]))
            latest = order["actual_delivery"] or order["estimated_delivery"]
            self.assertLessEqual(event_day, date.fromisoformat(latest))
        self.assertTrue(all(int(row["unit_price_inr"]) > 0 for row in read_rows("order_items.csv")))

    def test_policy_source_pdfs_and_manifest_exist_and_readable(self):
        manifest_path = PDF_OUTPUT / "policy_sources" / "manifest.csv"
        self.assertTrue(manifest_path.exists())
        with manifest_path.open(newline="", encoding="utf-8") as stream:
            manifest_rows = list(csv.DictReader(stream))
        self.assertEqual(len(manifest_rows), 10)
        for row in manifest_rows:
            self.assertEqual(row["status"], "success")
            target = PROJECT_ROOT / row["target_path"]
            self.assertTrue(target.exists(), f"Target file missing: {target}")
            self.assertGreater(target.stat().st_size, 0)
            self.assertGreater(int(row["pages"]), 0)
            self.assertGreater(int(row["character_count"]), 0)
            if row["marketplace"] == "Amazon.com":
                self.assertIn("/excluded/", row["target_path"])

    def test_clean_vector_store_policy_pdfs_exist(self):
        clean_dir = PDF_OUTPUT / "clean_policies"
        expected = [
            "AMZ-IN-RETURNS.pdf", "AMZ-IN-FBA-FAQ.pdf", "AMZ-IN-SELLER-REPLACEMENTS.pdf",
            "AMZ-IN-SELLER-CANCEL.pdf", "AMZ-IN-CUSTOMER-CARE.pdf", "AMZ-IN-BUSINESS-RETURNS.pdf",
            "FLIPKART-RETURNS.pdf", "FLIPKART-RETURN-PROCESS.pdf", "MYNTRA-REFUND-POLICY.pdf"
        ]
        for name in expected:
            p = clean_dir / name
            self.assertTrue(p.exists(), f"Missing clean PDF: {name}")
            self.assertGreater(p.stat().st_size, 0)
        self.assertTrue((clean_dir / "excluded" / "AMZ-US-RETURNS-EXCLUDED.pdf").exists())


if __name__ == "__main__":
    unittest.main()
