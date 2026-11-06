"""Chunk only versioned, synthetic, development-only policy source files."""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from backend.app.policy_documents import build_policy_chunks, write_policy_chunks

if __name__ == "__main__":
    chunks = build_policy_chunks()
    jsonl_path, csv_path = write_policy_chunks(chunks)
    print(f"Created {len(chunks)} chunks from {len({row['document_id'] for row in chunks})} documents.")
    print(f"JSONL: {jsonl_path.relative_to(PROJECT_ROOT)}")
    print(f"CSV: {csv_path.relative_to(PROJECT_ROOT)}")
