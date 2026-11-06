"""Local HTTP tests for the development-only RAG evaluation endpoints."""

import sys
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from backend.app.main import app  # noqa: E402


class RagEvaluationApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)

    def test_health(self):
        response = self.client.get("/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["environment"], "development-only")

    def test_single_query_returns_evidence_and_label_scores(self):
        response = self.client.post("/rag/evaluate", json={
            "query": "What should support do when the applicable policy version is missing?",
            "expected_document_id": "DEMO-EVIDENCE-GAPS",
            "expected_policy_version": "1.0.0",
            "expected_section_title": "Applicable policy version missing",
            "methods": ["keyword"],
            "top_k": 3,
        })
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        hit = body["cases"][0]["methods"]["keyword"]["hits"][0]
        self.assertEqual(hit["document_id"], "DEMO-EVIDENCE-GAPS")
        self.assertEqual(hit["policy_version"], "1.0.0")
        self.assertTrue(hit["excerpt"])
        self.assertTrue(body["cases"][0]["methods"]["keyword"]["evaluation"]["expected_section_at_1"])

    def test_labeled_set_runs_default_eleven_cases(self):
        response = self.client.post("/rag/evaluate/labeled-set", json={"methods": ["keyword"], "top_k": 3})
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(len(body["cases"]), 11)
        self.assertEqual(body["metrics"]["keyword"]["expected_document_hit_at_k"], 1.0)

    def test_invalid_top_k_is_rejected(self):
        response = self.client.post("/rag/evaluate", json={"query": "test question", "top_k": 99})
        self.assertEqual(response.status_code, 422)


if __name__ == "__main__":
    unittest.main()
