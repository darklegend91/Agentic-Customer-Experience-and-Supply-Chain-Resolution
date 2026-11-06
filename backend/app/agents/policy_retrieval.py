"""Shared policy retrieval stage used by the specialist agents."""

from __future__ import annotations

from typing import Any

from ..tools.policy_tools import search_policy


def retrieve_policy_evidence(
    query: str,
    *,
    methods: list[str],
    top_k: int,
    locale: str = "en-IN",
) -> dict[str, Any]:
    result = search_policy(query, methods=methods, top_k=top_k, locale=locale)
    return {
        "status": result.get("status", "insufficient_data"),
        "results": result.get("results", {}),
        "collection": result.get("collection"),
        "corpus_scope": result.get("corpus_scope", "unknown"),
        "missing_fields": result.get("missing_fields", []),
    }


def policy_evidence_references(policy_evidence: dict[str, Any]) -> list[str]:
    references: set[str] = set()
    for hits in (policy_evidence.get("results") or {}).values():
        for hit in hits or []:
            references.add(
                "policy:{document_id}@{version}:{section}:{chunk}".format(
                    document_id=hit.get("document_id", "unknown"),
                    version=hit.get("policy_version", "unknown"),
                    section=hit.get("section_id", "unknown"),
                    chunk=hit.get("chunk_id", "unknown"),
                )
            )
    return sorted(references)
