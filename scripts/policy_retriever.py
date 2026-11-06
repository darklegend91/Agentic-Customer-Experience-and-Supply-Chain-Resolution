"""Compatibility command for versioned policy evidence retrieval."""

from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from backend.app.policy_retrieval import KeywordPolicyRetriever, format_evidence  # noqa: E402


if __name__ == "__main__":
    query = "What should support do when a delivery scan conflicts with a non-receipt report?"
    hits = KeywordPolicyRetriever().search(query, top_k=3)
    print(format_evidence(hits))
