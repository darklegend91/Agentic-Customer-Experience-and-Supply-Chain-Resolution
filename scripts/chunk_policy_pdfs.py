"""Chunk policy documents into structured RAG chunks (both clean knowledge base and raw sources)."""

import csv
import json
import re
from pathlib import Path
import pypdf

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
PDF_DIR = ROOT / "output" / "pdf"
CLEAN_KB_PDF = PDF_DIR / "marketplace_policy_knowledge_base.pdf"
RAW_MANIFEST = PDF_DIR / "policy_sources" / "manifest.csv"

CLEAN_CHUNKS_JSON = DATA_DIR / "policy_chunks.json"
CLEAN_CHUNKS_JSONL = DATA_DIR / "policy_chunks.jsonl"
RAW_CHUNKS_JSON = DATA_DIR / "raw_policy_chunks.json"


def recursive_chunk_text(text: str, max_chars: int = 700, overlap: int = 100) -> list[str]:
    """Split text cleanly using natural sentence or paragraph boundaries."""
    text = re.sub(r"[ \t]+", " ", text).strip()
    if not text:
        return []
    chunks = []
    start = 0
    while start < len(text):
        end = min(start + max_chars, len(text))
        if end < len(text):
            break_pt = max(text.rfind("\n", start, end), text.rfind(". ", start, end))
            if break_pt > start + int(max_chars * 0.4):
                end = break_pt + 1
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= len(text):
            break
        start = end - overlap
    return chunks


def chunk_clean_knowledge_base() -> list[dict]:
    """Chunk the clean, noise-free policy reference PDF."""
    if not CLEAN_KB_PDF.exists():
        raise FileNotFoundError(f"Clean KB PDF not found at {CLEAN_KB_PDF}. Run data/build_policy_knowledge_base.py first.")

    reader = pypdf.PdfReader(str(CLEAN_KB_PDF))
    chunks = []
    chunk_counter = 0

    for page_num, page in enumerate(reader.pages, start=1):
        txt = page.extract_text() or ""
        page_chunks = recursive_chunk_text(txt)

        for c_idx, content in enumerate(page_chunks, start=1):
            chunk_counter += 1
            # Infer marketplace tag from page/section context
            marketplace = "Amazon.in"
            if "Section 3: Cross-Platform" in content or "Flipkart" in content or "Myntra" in content:
                marketplace = "Cross-Platform"
            elif "Section 4: Quarantined" in content or "Amazon.com (US)" in content:
                marketplace = "Amazon.com"

            is_excluded = (marketplace == "Amazon.com")

            chunks.append({
                "chunk_id": f"KB-MKT-POL#p{page_num:02d}_c{c_idx:02d}",
                "document_id": "KB-MKT-POL-2026-V1",
                "marketplace": marketplace,
                "page_number": page_num,
                "chunk_index": c_idx,
                "source_pdf": "output/pdf/marketplace_policy_knowledge_base.pdf",
                "is_excluded": is_excluded,
                "character_count": len(content),
                "content": content,
            })

    with CLEAN_CHUNKS_JSON.open("w", encoding="utf-8") as f:
        json.dump(chunks, f, indent=2, ensure_ascii=False)

    with CLEAN_CHUNKS_JSONL.open("w", encoding="utf-8") as f:
        for c in chunks:
            f.write(json.dumps(c, ensure_ascii=False) + "\n")

    print(f"Generated {len(chunks)} clean, noise-free chunks from {CLEAN_KB_PDF.name}")
    print(f"Saved to {CLEAN_CHUNKS_JSON.relative_to(ROOT)} and {CLEAN_CHUNKS_JSONL.relative_to(ROOT)}")
    return chunks


def chunk_raw_sources() -> list[dict]:
    """Chunk the raw web page captures from manifest.csv."""
    if not RAW_MANIFEST.exists():
        return []

    with RAW_MANIFEST.open(newline="", encoding="utf-8") as f:
        manifest = list(csv.DictReader(f))

    raw_chunks = []
    chunk_counter = 0

    for doc in manifest:
        source_id = doc["source_id"]
        marketplace = doc["marketplace"]
        target_path = ROOT / doc["target_path"]
        is_excluded = (marketplace == "Amazon.com" or "EXCLUDED" in source_id)

        if not target_path.exists():
            continue

        reader = pypdf.PdfReader(str(target_path))
        doc_chunk_idx = 0

        for page_num, page in enumerate(reader.pages, start=1):
            page_text = page.extract_text() or ""
            for chunk_text in recursive_chunk_text(page_text):
                chunk_counter += 1
                doc_chunk_idx += 1
                raw_chunks.append({
                    "chunk_id": f"{source_id}#p{page_num:02d}_c{doc_chunk_idx:03d}",
                    "document_id": source_id,
                    "marketplace": marketplace,
                    "page_number": page_num,
                    "chunk_index": doc_chunk_idx,
                    "source_pdf": doc["target_path"],
                    "is_excluded": is_excluded,
                    "character_count": len(chunk_text),
                    "content": chunk_text,
                })

    with RAW_CHUNKS_JSON.open("w", encoding="utf-8") as f:
        json.dump(raw_chunks, f, indent=2, ensure_ascii=False)

    print(f"Generated {len(raw_chunks)} raw web-dump chunks -> {RAW_CHUNKS_JSON.relative_to(ROOT)}")
    return raw_chunks


if __name__ == "__main__":
    chunk_clean_knowledge_base()
    chunk_raw_sources()
