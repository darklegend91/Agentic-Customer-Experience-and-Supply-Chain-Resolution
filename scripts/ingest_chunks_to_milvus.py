"""Compatibility entry point for the safe Day 3 development-only indexer."""

from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from backend.app.milvus_index import index_policy_chunks  # noqa: E402
from backend.app.policy_documents import build_policy_chunks  # noqa: E402


if __name__ == "__main__":
    result = index_policy_chunks(build_policy_chunks())
    print(f"Indexed {result['chunk_count']} synthetic development passages into {result['collection']}.")
