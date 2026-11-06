"""Offline checks for the Day 3 classifier and policy retrieval baselines."""

import csv
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from backend.app.intent_classifier import build_pipeline  # noqa: E402
from backend.app.milvus_index import DEFAULT_COLLECTION, collection_name  # noqa: E402
from backend.app.policy_documents import build_policy_chunks  # noqa: E402
from backend.app.policy_retrieval import (  # noqa: E402
    KeywordPolicyRetriever,
    MilvusPolicyRetriever,
    format_evidence,
)


class Day3BaselineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.chunks = build_policy_chunks()

    def test_only_versioned_synthetic_dev_documents_are_chunked(self):
        self.assertEqual(len({row["document_id"] for row in self.chunks}), 5)
        self.assertGreater(len(self.chunks), 5)
        self.assertEqual(len({row["chunk_id"] for row in self.chunks}), len(self.chunks))
        for chunk in self.chunks:
            self.assertTrue(chunk["document_id"])
            self.assertEqual(chunk["policy_version"], "1.0.0")
            self.assertEqual(chunk["status"], "draft")
            self.assertEqual(chunk["environment_scope"], "development-only")
            self.assertTrue(chunk["synthetic_demo"])
            self.assertTrue(chunk["section_title"])
            self.assertTrue(chunk["content"])

    def test_keyword_baseline_returns_scoped_citations_and_excerpts(self):
        retriever = KeywordPolicyRetriever(self.chunks)
        queries = [
            ("Can a delivered scan prove receipt when a customer reports non-receipt?", "DEMO-DELIVERY-INVESTIGATION"),
            ("Can return eligibility be decided from category alone?", "DEMO-RETURN-ELIGIBILITY"),
            ("What should happen if the applicable policy version is missing?", "DEMO-EVIDENCE-GAPS"),
        ]
        for query, expected_document in queries:
            hits = retriever.search(query, top_k=3)
            self.assertTrue(any(hit["document_id"] == expected_document for hit in hits), query)
            for hit in hits:
                self.assertEqual(hit["policy_version"], "1.0.0")
                self.assertEqual(hit["environment_scope"], "development-only")
                self.assertTrue(hit["excerpt"])
        damage_hits = retriever.search("What should I do if my order is damaged?", top_k=3)
        self.assertEqual(damage_hits[0]["document_id"], "DEMO-SUPPORT-FAQ")
        self.assertEqual(damage_hits[0]["section_title"], "My item arrived damaged")
        self.assertIn("broken, or defective", damage_hits[0]["excerpt"])
        self.assertIn("policy_version=1.0.0", format_evidence(hits))

    def test_semantic_search_filter_is_restricted_to_development_drafts(self):
        expression = MilvusPolicyRetriever._filter("synthetic-fixture")
        self.assertIn('status == "draft"', expression)
        self.assertIn('environment_scope == "development-only"', expression)
        self.assertIn("synthetic_demo == true", expression)
        self.assertIn('marketplace == "synthetic-fixture"', expression)

    def test_index_collection_default_is_separate_from_existing_collection(self):
        self.assertEqual(DEFAULT_COLLECTION, "agentic_customer_support_dev_policies_v1")
        self.assertIn("_dev", collection_name())
        with patch.dict(os.environ, {"MILVUS_COLLECTION": "marketplace_policy_knowledge_base"}):
            with self.assertRaises(ValueError):
                collection_name()

    def test_classifier_pipeline_fits_and_predicts_a_label(self):
        model = build_pipeline()
        model.fit(
            ["Where is my order?", "Track my delivery", "Refund status please", "Where is my refund?"],
            ["order_status", "order_status", "refund_status", "refund_status"],
        )
        prediction = model.predict(["Please track my order"])[0]
        self.assertIn(prediction, {"order_status", "refund_status"})


if __name__ == "__main__":
    unittest.main()
