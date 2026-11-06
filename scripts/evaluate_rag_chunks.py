"""Evaluate chunk quality and retrieval performance (Hit@K, MRR, Guardrails)."""

import json
from pathlib import Path

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

ROOT = Path(__file__).resolve().parent.parent
CHUNKS_PATH = ROOT / "data" / "vector_store_chunks.json"

# Labelled evaluation set for retrieval quality benchmarking
BENCHMARK_CASES = [
    {
        "query": "My mixer grinder arrived with a broken outer box and won't turn on. Can I return it?",
        "expected_doc": "AMZ-IN-RETURNS",
        "expected_page": 1,
        "target_marketplace": "Amazon.in",
    },
    {
        "query": "Technician visit required for refrigerator or microwave cooling defect",
        "expected_doc": "AMZ-IN-RETURNS",
        "expected_page": 1,
        "target_marketplace": "Amazon.in",
    },
    {
        "query": "What is the return window for clothing and footwear?",
        "expected_doc": "AMZ-IN-RETURNS",
        "expected_page": 2,
        "target_marketplace": "Amazon.in",
    },
    {
        "query": "How are customer returns handled for FBA inventory by Amazon customer service?",
        "expected_doc": "AMZ-IN-FBA-FAQ",
        "expected_page": 1,
        "target_marketplace": "Amazon.in",
    },
    {
        "query": "Seller-fulfilled replacement out of stock fallback to full refund",
        "expected_doc": "AMZ-IN-SELLER-REPLACEMENTS",
        "expected_page": 1,
        "target_marketplace": "Amazon.in",
    },
    {
        "query": "How do I cancel an order that is already shipped and handed to the carrier?",
        "expected_doc": "AMZ-IN-SELLER-CANCEL",
        "expected_page": 1,
        "target_marketplace": "Amazon.in",
    },
    {
        "query": "Tracking says delivered but I did not receive the package. Escalation SLA",
        "expected_doc": "AMZ-IN-CUSTOMER-CARE",
        "expected_page": 1,
        "target_marketplace": "Amazon.in",
    },
    {
        "query": "GST invoice adjustment and credit note for Amazon Business returns",
        "expected_doc": "AMZ-IN-BUSINESS-RETURNS",
        "expected_page": 1,
        "target_marketplace": "Amazon.in",
    },
    {
        "query": "What is the return window for Flipkart lifestyle items?",
        "expected_doc": "FLIPKART-RETURNS",
        "expected_page": 1,
        "target_marketplace": "Flipkart",
    },
    {
        "query": "Myntra 14 day return policy for apparel and footwear",
        "expected_doc": "MYNTRA-REFUND-POLICY",
        "expected_page": 1,
        "target_marketplace": "Myntra",
    },
]


def evaluate_chunk_structural_quality(chunks: list[dict]) -> dict:
    """Analyze chunk lengths, information density, and metadata completeness."""
    lengths = [c["character_count"] for c in chunks]
    short_chunks = [c for c in chunks if c["character_count"] < 150]
    long_chunks = [c for c in chunks if c["character_count"] > 1000]

    missing_meta = 0
    for c in chunks:
        if not c.get("document_id") or not c.get("page_number") or not c.get("chunk_id") or not c.get("marketplace"):
            missing_meta += 1

    return {
        "total_chunks": len(chunks),
        "avg_char_length": round(sum(lengths) / len(lengths), 1) if lengths else 0,
        "min_char_length": min(lengths) if lengths else 0,
        "max_char_length": max(lengths) if lengths else 0,
        "short_fragments_under_150_chars": len(short_chunks),
        "long_chunks_over_1000_chars": len(long_chunks),
        "metadata_completeness_pct": round(100.0 * (len(chunks) - missing_meta) / len(chunks), 1) if chunks else 0.0,
    }


def evaluate_retrieval_performance(chunks: list[dict]) -> dict:
    """Compute Hit@1, Hit@3, MRR, and Guardrail Compliance."""
    hits_at_1 = 0
    hits_at_3 = 0
    reciprocal_ranks = []
    guardrail_violations = 0

    for case in BENCHMARK_CASES:
        query = case["query"]
        target_mkt = case["target_marketplace"]
        exp_doc = case["expected_doc"]

        # Apply metadata filter
        filtered = [c for c in chunks if c["marketplace"] == target_mkt and not c.get("is_excluded", False)]
        if not filtered:
            continue

        corpus = [c["content"] for c in filtered]
        vectorizer = TfidfVectorizer(stop_words="english", ngram_range=(1, 2))
        matrix = vectorizer.fit_transform(corpus)
        sims = cosine_similarity(vectorizer.transform([query]), matrix)[0]

        top_indices = sims.argsort()[-3:][::-1]
        top_docs = [filtered[i]["document_id"] for i in top_indices]

        # Check for guardrail violation
        for i in top_indices:
            c = filtered[i]
            if c["marketplace"] != target_mkt or c.get("is_excluded", False):
                guardrail_violations += 1

        # Check Hit@1
        if top_docs and top_docs[0] == exp_doc:
            hits_at_1 += 1

        # Check Hit@3
        if exp_doc in top_docs[:3]:
            hits_at_3 += 1

        # Check Reciprocal Rank
        try:
            rank = top_docs.index(exp_doc) + 1
            reciprocal_ranks.append(1.0 / rank)
        except ValueError:
            reciprocal_ranks.append(0.0)

    total_queries = len(BENCHMARK_CASES)
    return {
        "benchmark_queries": total_queries,
        "hit_at_1": f"{hits_at_1}/{total_queries} ({hits_at_1 / total_queries * 100:.1f}%)",
        "hit_at_3": f"{hits_at_3}/{total_queries} ({hits_at_3 / total_queries * 100:.1f}%)",
        "mean_reciprocal_rank_mrr": round(sum(reciprocal_ranks) / len(reciprocal_ranks), 3) if reciprocal_ranks else 0.0,
        "guardrail_violations": guardrail_violations,
    }


def main():
    if not CHUNKS_PATH.exists():
        raise FileNotFoundError(f"Chunks file missing: {CHUNKS_PATH}. Run data/build_vector_store.py first.")

    with CHUNKS_PATH.open(encoding="utf-8") as f:
        chunks = json.load(f)

    print("=" * 60)
    print(" 1. CHUNK STRUCTURAL QUALITY AUDIT")
    print("=" * 60)
    quality_stats = evaluate_chunk_structural_quality(chunks)
    for k, v in quality_stats.items():
        print(f"  {k:35}: {v}")

    print("\n" + "=" * 60)
    print(" 2. RETRIEVAL ACCURACY & GUARDRAIL BENCHMARK")
    print("=" * 60)
    retrieval_stats = evaluate_retrieval_performance(chunks)
    for k, v in retrieval_stats.items():
        print(f"  {k:35}: {v}")


if __name__ == "__main__":
    main()

