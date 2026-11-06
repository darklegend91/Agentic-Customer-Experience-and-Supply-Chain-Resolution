"""Load clean policy PDFs, extract text by page, chunk with metadata, and prepare vector store."""

import json
from pathlib import Path

import pypdf
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

ROOT = Path(__file__).resolve().parent.parent
PDF_DIR = ROOT / "output" / "pdf" / "clean_policies"
OUTPUT_JSON = ROOT / "data" / "vector_store_chunks.json"
OUTPUT_JSONL = ROOT / "data" / "vector_store_chunks.jsonl"


def extract_and_chunk_pdf(pdf_path: Path, is_excluded: bool = False, max_chars: int = 700, overlap: int = 100) -> list[dict]:
    reader = pypdf.PdfReader(str(pdf_path))
    doc_id = pdf_path.stem
    chunks = []
    chunk_idx = 0

    marketplace = "Amazon.in"
    if "FLIPKART" in doc_id:
        marketplace = "Flipkart"
    elif "MYNTRA" in doc_id:
        marketplace = "Myntra"
    elif "AMZ-US" in doc_id:
        marketplace = "Amazon.com"

    for page_num, page in enumerate(reader.pages, start=1):
        text = page.extract_text() or ""
        text = " ".join(text.split())
        start = 0
        while start < len(text):
            end = min(start + max_chars, len(text))
            if end < len(text):
                break_pt = max(text.rfind(". ", start, end), text.rfind("; ", start, end))
                if break_pt > start + int(max_chars * 0.4):
                    end = break_pt + 1
            chunk_content = text[start:end].strip()
            if chunk_content:
                chunk_idx += 1
                chunk_id = f"{doc_id}#p{page_num:02d}_c{chunk_idx:02d}"
                chunks.append({
                    "chunk_id": chunk_id,
                    "document_id": doc_id,
                    "marketplace": marketplace,
                    "page_number": page_num,
                    "chunk_index": chunk_idx,
                    "is_excluded": is_excluded,
                    "source_file": str(pdf_path.relative_to(ROOT)),
                    "character_count": len(chunk_content),
                    "content": chunk_content,
                })
            if end >= len(text):
                break
            start = end - overlap
    return chunks


def build_vector_store():
    all_chunks = []
    pdf_files = list(PDF_DIR.glob("*.pdf"))
    excluded_files = list((PDF_DIR / "excluded").glob("*.pdf"))

    print(f"Loading {len(pdf_files)} active policy PDFs + {len(excluded_files)} quarantined PDFs...")

    for pdf in sorted(pdf_files):
        c = extract_and_chunk_pdf(pdf, is_excluded=False)
        all_chunks.extend(c)
        print(f"  [Active] {pdf.name} -> {len(c)} chunks")

    for pdf in sorted(excluded_files):
        c = extract_and_chunk_pdf(pdf, is_excluded=True)
        all_chunks.extend(c)
        print(f"  [Quarantined] {pdf.name} -> {len(c)} chunks")

    with OUTPUT_JSON.open("w", encoding="utf-8") as f:
        json.dump(all_chunks, f, indent=2, ensure_ascii=False)

    with OUTPUT_JSONL.open("w", encoding="utf-8") as f:
        for c in all_chunks:
            f.write(json.dumps(c, ensure_ascii=False) + "\n")

    print(f"\nVector Store Index ready: {len(all_chunks)} chunks written to {OUTPUT_JSON.relative_to(ROOT)}")
    return all_chunks


class PolicyVectorStore:
    """Vector store search interface with metadata guardrails."""
    def __init__(self, chunks_path: Path = OUTPUT_JSON):
        with chunks_path.open(encoding="utf-8") as f:
            self.chunks = json.load(f)

    def similarity_search(self, query: str, marketplace: str = "Amazon.in", top_k: int = 3) -> list[dict]:
        # Guardrail: strict metadata filtering
        allowed = [c for c in self.chunks if c["marketplace"] == marketplace and not c["is_excluded"]]
        if not allowed:
            return []

        corpus = [c["content"] for c in allowed]
        vectorizer = TfidfVectorizer(stop_words="english", ngram_range=(1, 2))
        matrix = vectorizer.fit_transform(corpus)
        sims = cosine_similarity(vectorizer.transform([query]), matrix)[0]

        top_idxs = sims.argsort()[-top_k:][::-1]
        results = []
        for rank, idx in enumerate(top_idxs, 1):
            if sims[idx] <= 0.0:
                continue
            item = dict(allowed[idx])
            item["score"] = round(float(sims[idx]), 4)
            item["rank"] = rank
            results.append(item)
        return results


if __name__ == "__main__":
    chunks = build_vector_store()
    store = PolicyVectorStore()

    test_queries = [
        "technician visit for refrigerator or television defect",
        "how to cancel order that is already shipped",
        "seller fulfilled replacement out of stock fallback"
    ]
    print("\n--- Testing Vector Store Similarity Search ---")
    for q in test_queries:
        res = store.similarity_search(q, marketplace="Amazon.in", top_k=1)
        if res:
            top = res[0]
            print(f"\nQuery: '{q}'")
            print(f"Top Result [{top['document_id']}, Page {top['page_number']}] (Score: {top['score']}):")
            print(f"File: {top['source_file']}")
            print(f"Snippet: {top['content'][:200]}...")

