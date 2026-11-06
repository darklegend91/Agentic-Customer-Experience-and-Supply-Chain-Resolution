"""Version-aware dev retrieval baselines: Milvus semantic and local TF-IDF keyword."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from sklearn.feature_extraction.text import ENGLISH_STOP_WORDS, TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from .embeddings import encode_texts
from .milvus_index import OUTPUT_FIELDS, VECTOR_FIELD, collection_name, create_client
from .policy_documents import OUTPUT_DIR


CHUNKS_JSONL = OUTPUT_DIR / "policy_chunks_v1.jsonl"
DEV_MARKETPLACE = "synthetic-fixture"
_NEGATION_WORDS = {"no", "not", "nor", "never", "neither", "without"}
_KEYWORD_STOP_WORDS = sorted(set(ENGLISH_STOP_WORDS) - _NEGATION_WORDS)


def load_chunks(path: Path = CHUNKS_JSONL) -> list[dict[str, Any]]:
    if not path.exists():
        raise FileNotFoundError(f"Missing {path}; run scripts/chunk_versioned_policies.py first")
    chunks = []
    with path.open(encoding="utf-8") as stream:
        for line in stream:
            if line.strip():
                chunks.append(json.loads(line))
    return chunks


def _allowed_dev_record(
    row: dict[str, Any],
    marketplace: str = DEV_MARKETPLACE,
    locale: str | None = None,
) -> bool:
    return (
        row.get("environment_scope") == "development-only"
        and row.get("synthetic_demo") is True
        and row.get("status") == "draft"
        and row.get("marketplace") == marketplace
        and (locale is None or str(row.get("locale") or "").casefold() == locale.casefold())
    )


def _validate_locale(locale: str) -> str:
    value = str(locale or "").strip()
    if not re.fullmatch(r"[a-z]{2}-[A-Z]{2}", value):
        raise ValueError("locale must use the language-REGION format, such as en-IN")
    return value


def _to_result(row: dict[str, Any], score: float, rank: int) -> dict[str, Any]:
    def json_list(field: str) -> list[str]:
        value = row.get(field)
        if isinstance(value, list):
            return [str(item) for item in value]
        try:
            parsed = json.loads(value) if isinstance(value, str) else []
        except (TypeError, ValueError):
            parsed = []
        return [str(item) for item in parsed] if isinstance(parsed, list) else []

    return {
        "rank": rank,
        "score": float(score),
        "document_id": row.get("document_id", ""),
        "policy_id": row.get("policy_id", ""),
        "policy_version": row.get("policy_version", ""),
        "artifact_type": row.get("artifact_type", ""),
        "status": row.get("status", ""),
        "marketplace": row.get("marketplace", ""),
        "environment_scope": row.get("environment_scope", ""),
        "section_id": row.get("section_id", ""),
        "section_title": row.get("section_title", ""),
        "chunk_id": row.get("chunk_id", ""),
        "source_uri": row.get("source_uri", ""),
        "source_path": row.get("source_path", ""),
        "source_file_sha256": row.get("source_file_sha256", ""),
        "jurisdiction": row.get("jurisdiction", ""),
        "locale": row.get("locale", ""),
        "effective_from": row.get("effective_from", ""),
        "effective_to": row.get("effective_to", ""),
        "synthetic_demo": bool(row.get("synthetic_demo", False)),
        "intents": json_list("intents_json"),
        "categories": json_list("categories_json"),
        "excerpt": row.get("content", ""),
    }


class KeywordPolicyRetriever:
    """A small TF-IDF keyword baseline over the same scoped policy chunks."""

    def __init__(self, chunks: list[dict[str, Any]] | None = None):
        self.chunks = chunks if chunks is not None else load_chunks()
        self.eligible = [
            row for row in self.chunks
            if _allowed_dev_record(row, str(row.get("marketplace", "")))
        ]
        self.vectorizer: TfidfVectorizer | None = None
        self.matrix = None
        if self.eligible:
            corpus = [
                f"{row.get('title', '')}. {row.get('section_title', '')}. {row.get('content', '')}"
                for row in self.eligible
            ]
            self.vectorizer = TfidfVectorizer(
                lowercase=True,
                strip_accents="unicode",
                stop_words=_KEYWORD_STOP_WORDS,
                ngram_range=(1, 2),
                sublinear_tf=True,
            )
            self.matrix = self.vectorizer.fit_transform(corpus)

    def search(
        self,
        query: str,
        *,
        top_k: int = 3,
        marketplace: str = DEV_MARKETPLACE,
        locale: str = "en-IN",
    ) -> list[dict[str, Any]]:
        query = (query or "").strip()
        if not query:
            raise ValueError("Query must not be empty")
        locale = _validate_locale(locale)
        if not self.eligible or self.vectorizer is None or self.matrix is None:
            return []
        # Fit the corpus representation once per retriever instance; queries only
        # transform the input, avoiding a full TF-IDF rebuild on every request.
        query_vector = self.vectorizer.transform([query])
        scores = cosine_similarity(query_vector, self.matrix)[0]
        allowed = [
            idx for idx, row in enumerate(self.eligible)
            if row.get("marketplace") == marketplace
            and str(row.get("locale") or "").casefold() == locale.casefold()
        ]
        ranked = sorted(allowed, key=lambda idx: (-float(scores[idx]), self.eligible[idx]["chunk_id"]))
        results = []
        for idx in ranked:
            score = float(scores[idx])
            if score <= 0:
                continue
            results.append(_to_result(self.eligible[idx], score, len(results) + 1))
            if len(results) >= top_k:
                break
        return results


class MilvusPolicyRetriever:
    """Milvus semantic retrieval restricted to the versioned synthetic dev corpus."""

    def __init__(self, *, client=None, collection: str | None = None, model_name: str | None = None):
        self.client = client or create_client()
        self.owns_client = client is None
        self.collection = collection or collection_name()
        if "_dev" not in self.collection.lower():
            raise ValueError("This retrieval baseline only permits a dev-named Milvus collection")
        self.model_name = model_name
        if not self.client.has_collection(collection_name=self.collection):
            raise FileNotFoundError(f"Milvus collection {self.collection!r} does not exist; index dev policies first")
        self.client.load_collection(collection_name=self.collection)

    @staticmethod
    def _filter(marketplace: str, locale: str) -> str:
        # JSON string escaping matches Milvus string-literal escaping for these scalar filters.
        escaped_marketplace = json.dumps(marketplace)
        escaped_locale = json.dumps(locale)
        return (
            'status == "draft" and environment_scope == "development-only" '
            f"and synthetic_demo == true and marketplace == {escaped_marketplace} "
            f"and locale == {escaped_locale}"
        )

    def search(
        self,
        query: str,
        *,
        top_k: int = 3,
        marketplace: str = DEV_MARKETPLACE,
        locale: str = "en-IN",
    ) -> list[dict[str, Any]]:
        query = (query or "").strip()
        if not query:
            raise ValueError("Query must not be empty")
        locale = _validate_locale(locale)
        vector = encode_texts([query], model_name=self.model_name)[0]
        hits = self.client.search(
            collection_name=self.collection,
            data=[vector],
            anns_field=VECTOR_FIELD,
            filter=self._filter(marketplace, locale),
            limit=top_k,
            output_fields=OUTPUT_FIELDS,
            search_params={"metric_type": "COSINE", "params": {}},
            timeout=10,
        )
        results = []
        for hit in hits[0] if hits else []:
            row = dict(hit.get("entity") or {})
            # Filter again in application code as a fail-closed check.
            if not _allowed_dev_record(row, marketplace, locale):
                continue
            score = float(hit.get("distance", hit.get("score", 0.0)))
            results.append(_to_result(row, score, len(results) + 1))
        return results

    def close(self) -> None:
        if self.owns_client:
            self.client.close()


def format_evidence(results: list[dict[str, Any]]) -> str:
    """Render retrieved excerpts with document/version/section citations."""
    if not results:
        return "No matching development policy evidence found."
    blocks = []
    for item in results:
        blocks.append(
            f"[Evidence {item['rank']}] document_id={item['document_id']} "
            f"policy_version={item['policy_version']} section={item['section_title']} "
            f"chunk_id={item['chunk_id']} score={item['score']:.4f}\n{item['excerpt']}"
        )
    return "\n\n".join(blocks)
