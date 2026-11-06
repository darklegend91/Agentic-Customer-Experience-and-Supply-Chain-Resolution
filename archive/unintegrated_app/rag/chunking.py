import tiktoken
from pathlib import Path
from datetime import datetime
from typing import List, Dict

# Encoder for LLM context (adjust if you target a different model)
ENCODER = tiktoken.get_encoding("cl100k_base")
MAX_TOKENS = 500
OVERLAP = 50

def _token_len(text: str) -> int:
    return len(ENCODER.encode(text))

def chunk_document(text: str, source_file: str) -> List[Dict]:
    """Create token‑aware overlapping chunks.
    Returns list of dicts with metadata required for Milvus storage.
    """
    tokens = ENCODER.encode(text)
    chunks = []
    i = 0
    idx = 0
    while i < len(tokens):
        window = tokens[i : i + MAX_TOKENS]
        chunk_text = ENCODER.decode(window)
        chunks.append(
            {
                "id": f"{Path(source_file).name}#c{idx}",
                "text": chunk_text,
                "source_file": source_file,
                "chunk_idx": idx,
                "timestamp": datetime.utcnow().isoformat(),
                "token_count": len(window),
            }
        )
        i += MAX_TOKENS - OVERLAP
        idx += 1
    return chunks

