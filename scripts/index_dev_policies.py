"""Create/upsert the isolated Milvus development index for synthetic policy chunks."""

from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from backend.app.milvus_index import index_policy_chunks  # noqa: E402
from backend.app.policy_documents import build_policy_chunks  # noqa: E402


if __name__ == "__main__":
    result = index_policy_chunks(build_policy_chunks())
    print(f"Indexed {result['chunk_count']} passages across {result['document_count']} documents.")
    print(f"Collection: {result['collection']} (created={result['collection_created']})")
    print(f"Model: {result['embedding_model']} ({result['embedding_dimension']} dimensions)")
    print(f"Scope: {result['writes_scoped_to']}")
