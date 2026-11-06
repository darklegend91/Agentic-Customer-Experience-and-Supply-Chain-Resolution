"""Shared policy search over the synthetic, development-only draft corpus."""

from __future__ import annotations

import threading
from typing import Any, Literal

from ..api.schemas.evidence import PolicySearchResponse
from ..milvus_index import collection_name
from ..policy_retrieval import KeywordPolicyRetriever, MilvusPolicyRetriever
from ..runtime import require_local_development


PolicyMethod = Literal["semantic", "keyword"]
_retriever_lock = threading.RLock()
_semantic_retriever: MilvusPolicyRetriever | None = None
_keyword_retriever: KeywordPolicyRetriever | None = None


def _get_semantic_retriever() -> MilvusPolicyRetriever:
    global _semantic_retriever
    with _retriever_lock:
        if _semantic_retriever is None:
            _semantic_retriever = MilvusPolicyRetriever()
        return _semantic_retriever


def _get_keyword_retriever() -> KeywordPolicyRetriever:
    global _keyword_retriever
    with _retriever_lock:
        if _keyword_retriever is None:
            _keyword_retriever = KeywordPolicyRetriever()
        return _keyword_retriever


def close_policy_retrievers() -> None:
    """Release process-level Milvus resources on API or MCP shutdown."""
    global _semantic_retriever, _keyword_retriever
    with _retriever_lock:
        if _semantic_retriever is not None:
            _semantic_retriever.close()
        _semantic_retriever = None
        _keyword_retriever = None


def search_policy(
    query: str,
    *,
    top_k: int = 3,
    methods: list[PolicyMethod] | None = None,
    locale: str = "en-IN",
) -> dict[str, Any]:
    """Search draft synthetic passages; results are not approved customer policy."""
    require_local_development()
    selected = list(dict.fromkeys(["semantic", "keyword"] if methods is None else methods))
    if not selected or any(method not in {"semantic", "keyword"} for method in selected):
        raise ValueError("Select semantic, keyword, or both policy methods")
    if not 1 <= top_k <= 10:
        raise ValueError("top_k must be between 1 and 10")

    results = {}
    for method in selected:
        retriever = _get_semantic_retriever() if method == "semantic" else _get_keyword_retriever()
        if method == "semantic":
            # MilvusClient is retained for process reuse; serialize operations on
            # that client until a bounded client pool is configured for serving.
            with _retriever_lock:
                results[method] = retriever.search(query, top_k=top_k, locale=locale)
        else:
            results[method] = retriever.search(query, top_k=top_k, locale=locale)

    missing_fields = [] if any(results.values()) else ["relevant_policy_passage"]
    result = {
        "status": "found" if not missing_fields else "insufficient_data",
        "results": results,
        "collection": collection_name() if "semantic" in selected else None,
        "corpus_scope": "synthetic development-only draft documents; not production policy",
        "missing_fields": missing_fields,
    }
    return PolicySearchResponse.model_validate(result).model_dump(mode="json")
