"""Tests the combined read-only order and policy-evidence endpoint."""

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from backend.app.main import app  # noqa: E402
from backend.app.order_lookup import OrderNotFoundError  # noqa: E402


def sample_hit():
    return {
        "rank": 1,
        "score": 0.8,
        "document_id": "DEMO-SUPPORT-FAQ",
        "policy_id": "",
        "policy_version": "1.0.0",
        "artifact_type": "faq",
        "status": "draft",
        "marketplace": "synthetic-fixture",
        "environment_scope": "development-only",
        "section_id": "S02",
        "section_title": "Where is my order?",
        "chunk_id": "chunk-test",
        "source_uri": "synthetic://test",
        "source_path": "knowledge_base/faqs/test/1.0.0.md",
        "source_file_sha256": "a" * 64,
        "excerpt": "Report the recorded order status and delivery event.",
    }


class FakeRetriever:
    def search(self, query, top_k=3):
        return [sample_hit()]

    def close(self):
        pass


class SupportInvestigationApiTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        self.order = {
            "source_system": "Neon Postgres",
            "as_of": "2026-11-02T00:00:00Z",
            "status": "found",
            "order": {"order_id": "ORD-ID-test000001", "status": "shipped", "marketplace": "Amazon.in"},
            "items": [{"item_id": "ITEM-1", "product_name": "Fixture item"}],
            "delivery_events": [],
            "returns_refunds": [],
            "evidence_refs": {"order": ["order:ORD-ID-test000001"], "items": ["item:ITEM-1"], "delivery_events": [], "returns_refunds": []},
        }

    @patch("backend.app.main.KeywordPolicyRetriever", return_value=FakeRetriever())
    @patch("backend.app.main.MilvusPolicyRetriever", return_value=FakeRetriever())
    @patch("backend.app.main.lookup_order_readonly")
    def test_combines_order_and_policy_evidence_without_claiming_policy_applicability(self, lookup, _semantic, _keyword):
        lookup.return_value = self.order
        response = self.client.post("/support/investigate", json={
            "order_id": "ORD-ID-test000001",
            "query": "Where is my order?",
            "top_k": 1,
            "methods": ["semantic", "keyword"],
        })
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["order_evidence"]["order"]["order_id"], "ORD-ID-test000001")
        self.assertEqual(body["milvus_collection"], "agentic_customer_support_dev_policies_v1")
        self.assertEqual(body["policy_evidence"]["semantic"][0]["policy_version"], "1.0.0")
        self.assertIn("not approved policy", body["policy_scope_notice"])
        self.assertNotIn("customer_id", body["order_evidence"]["order"])

    @patch("backend.app.main.lookup_order_readonly", side_effect=OrderNotFoundError("not found"))
    def test_missing_order_returns_404_before_policy_search(self, lookup):
        response = self.client.post("/support/investigate", json={
            "order_id": "ORD-ID-not-found",
            "query": "Where is my order?",
            "methods": ["keyword"],
        })
        self.assertEqual(response.status_code, 404)


if __name__ == "__main__":
    unittest.main()
