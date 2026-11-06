"""Evaluate Milvus semantic retrieval against a local TF-IDF keyword baseline."""

from __future__ import annotations

import csv
import json
from pathlib import Path
import sys
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from backend.app.milvus_index import collection_name  # noqa: E402
from backend.app.policy_retrieval import KeywordPolicyRetriever, MilvusPolicyRetriever  # noqa: E402


EVAL_PATH = PROJECT_ROOT / "data" / "processed" / "rag_policy_evaluation_v1.csv"
OUTPUT_DIR = PROJECT_ROOT / "data" / "processed"
TOP_K = 3


def read_cases(path: Path = EVAL_PATH) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as stream:
        cases = list(csv.DictReader(stream))
    if not cases:
        raise ValueError(f"No retrieval evaluation cases in {path}")
    return cases


def metrics(cases: list[dict[str, str]], outputs: list[list[dict[str, Any]]]) -> dict[str, Any]:
    hit1 = hit3 = section_hit1 = version_hit1 = 0
    reciprocal_ranks = []
    total_hits = 0
    scope_compliant_hits = 0
    citation_complete_hits = 0
    for case, hits in zip(cases, outputs):
        total_hits += len(hits)
        for hit in hits:
            if (
                hit.get("status") == "draft"
                and hit.get("environment_scope") == "development-only"
                and hit.get("marketplace") == "synthetic-fixture"
            ):
                scope_compliant_hits += 1
            if hit.get("document_id") and hit.get("policy_version") and hit.get("excerpt"):
                citation_complete_hits += 1
        docs = [hit.get("document_id", "") for hit in hits]
        expected_doc = case["expected_document_id"]
        if docs and docs[0] == expected_doc:
            hit1 += 1
            if hits[0].get("section_title") == case["expected_section_title"]:
                section_hit1 += 1
            if hits[0].get("policy_version") == case["expected_policy_version"]:
                version_hit1 += 1
        if expected_doc in docs[:TOP_K]:
            hit3 += 1
        rank = next((index + 1 for index, doc_id in enumerate(docs[:TOP_K]) if doc_id == expected_doc), None)
        reciprocal_ranks.append(1 / rank if rank else 0.0)
    total = len(cases)
    return {
        "query_count": total,
        "hit_at_1": hit1 / total,
        "hit_at_3": hit3 / total,
        "mrr_at_3": sum(reciprocal_ranks) / total,
        "expected_section_at_1": section_hit1 / total,
        "expected_version_at_1": version_hit1 / total,
        "scope_compliance": scope_compliant_hits / total_hits if total_hits else 1.0,
        "citation_metadata_completeness": citation_complete_hits / total_hits if total_hits else 1.0,
    }


def main() -> None:
    cases = read_cases()
    keyword = KeywordPolicyRetriever()
    keyword_outputs = [keyword.search(row["query"], top_k=TOP_K) for row in cases]

    semantic = MilvusPolicyRetriever()
    try:
        semantic_outputs = [semantic.search(row["query"], top_k=TOP_K) for row in cases]
    finally:
        semantic.close()

    results = {"keyword": metrics(cases, keyword_outputs), "semantic_milvus": metrics(cases, semantic_outputs)}
    results["evaluation_set"] = str(EVAL_PATH.relative_to(PROJECT_ROOT))
    results["collection"] = collection_name()
    results["corpus_scope"] = "synthetic development-only draft policies; not a production policy benchmark"
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    metrics_path = OUTPUT_DIR / "rag_retrieval_metrics_v1.json"
    metrics_path.write_text(json.dumps(results, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    predictions_path = OUTPUT_DIR / "rag_retrieval_predictions_v1.csv"
    with predictions_path.open("w", newline="", encoding="utf-8") as stream:
        fields = [
            "case_id", "query", "expected_document_id", "expected_policy_version", "expected_section_title",
            "keyword_document_at_1", "keyword_version_at_1", "keyword_section_at_1", "keyword_hit_at_1", "keyword_hit_at_3",
            "semantic_document_at_1", "semantic_version_at_1", "semantic_section_at_1", "semantic_excerpt_at_1",
            "semantic_hit_at_1", "semantic_hit_at_3",
        ]
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for case, keyword_hits, semantic_hits in zip(cases, keyword_outputs, semantic_outputs):
            keyword_top = keyword_hits[0] if keyword_hits else {}
            semantic_top = semantic_hits[0] if semantic_hits else {}
            expected = case["expected_document_id"]
            writer.writerow({
                **case,
                "keyword_document_at_1": keyword_top.get("document_id", ""),
                "keyword_version_at_1": keyword_top.get("policy_version", ""),
                "keyword_section_at_1": keyword_top.get("section_title", ""),
                "keyword_hit_at_1": str(bool(keyword_top and keyword_top.get("document_id") == expected)).lower(),
                "keyword_hit_at_3": str(any(hit.get("document_id") == expected for hit in keyword_hits[:TOP_K])).lower(),
                "semantic_document_at_1": semantic_top.get("document_id", ""),
                "semantic_version_at_1": semantic_top.get("policy_version", ""),
                "semantic_section_at_1": semantic_top.get("section_title", ""),
                "semantic_excerpt_at_1": semantic_top.get("excerpt", ""),
                "semantic_hit_at_1": str(bool(semantic_top and semantic_top.get("document_id") == expected)).lower(),
                "semantic_hit_at_3": str(any(hit.get("document_id") == expected for hit in semantic_hits[:TOP_K])).lower(),
            })

    print(json.dumps(results, indent=2, ensure_ascii=False))
    print(f"Predictions: {predictions_path.relative_to(PROJECT_ROOT)}")


if __name__ == "__main__":
    main()
