"""Isolated Milvus development collection for versioned synthetic policy chunks."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from pymilvus import DataType, MilvusClient

from .embeddings import DEFAULT_MODEL, encode_texts
from .policy_documents import PROJECT_ROOT, build_policy_chunks, write_policy_chunks


DEFAULT_COLLECTION = "agentic_customer_support_dev_policies_v1"
VECTOR_FIELD = "embedding"
VECTOR_DIMENSION = 384
OUTPUT_FIELDS = [
    "chunk_id", "document_id", "policy_id", "policy_version", "artifact_type", "title",
    "status", "marketplace", "jurisdiction", "environment_scope", "synthetic_demo", "locale",
    "effective_from", "effective_to", "section_id", "section_title", "intents_json",
    "categories_json", "related_policy_ids_json", "source_uri", "source_path",
    "source_file_sha256", "content_sha256", "content",
]


def load_project_environment() -> None:
    for path in (PROJECT_ROOT / ".env", PROJECT_ROOT.parent / ".env"):
        if path.exists():
            load_dotenv(path, override=False)


def collection_name() -> str:
    name = os.getenv("MILVUS_COLLECTION", DEFAULT_COLLECTION).strip()
    if "_dev" not in name.lower():
        raise ValueError("Day 3 indexing is limited to a Milvus collection whose name contains '_dev'")
    if name == "marketplace_policy_knowledge_base":
        raise ValueError("Refusing to write into the existing unversioned policy collection")
    return name


def create_client() -> MilvusClient:
    load_project_environment()
    uri = os.getenv("MILVUS_URI", "").strip()
    token = os.getenv("MILVUS_TOKEN", "").strip()
    if not uri or not token:
        raise RuntimeError("Set MILVUS_URI and MILVUS_TOKEN in the local environment before Milvus operations")
    return MilvusClient(uri=uri, token=token, timeout=30)


def _schema(client: MilvusClient):
    schema = client.create_schema(auto_id=False, enable_dynamic_field=False)
    schema.add_field(field_name="chunk_id", datatype=DataType.VARCHAR, is_primary=True, max_length=80)
    schema.add_field(field_name=VECTOR_FIELD, datatype=DataType.FLOAT_VECTOR, dim=VECTOR_DIMENSION)
    schema.add_field(field_name="document_id", datatype=DataType.VARCHAR, max_length=128)
    schema.add_field(field_name="policy_id", datatype=DataType.VARCHAR, max_length=128)
    schema.add_field(field_name="policy_version", datatype=DataType.VARCHAR, max_length=32)
    schema.add_field(field_name="artifact_type", datatype=DataType.VARCHAR, max_length=32)
    schema.add_field(field_name="title", datatype=DataType.VARCHAR, max_length=512)
    schema.add_field(field_name="status", datatype=DataType.VARCHAR, max_length=32)
    schema.add_field(field_name="marketplace", datatype=DataType.VARCHAR, max_length=128)
    schema.add_field(field_name="jurisdiction", datatype=DataType.VARCHAR, max_length=32)
    schema.add_field(field_name="environment_scope", datatype=DataType.VARCHAR, max_length=64)
    schema.add_field(field_name="synthetic_demo", datatype=DataType.BOOL)
    schema.add_field(field_name="locale", datatype=DataType.VARCHAR, max_length=32)
    schema.add_field(field_name="effective_from", datatype=DataType.VARCHAR, max_length=64)
    schema.add_field(field_name="effective_to", datatype=DataType.VARCHAR, max_length=64)
    schema.add_field(field_name="section_id", datatype=DataType.VARCHAR, max_length=32)
    schema.add_field(field_name="section_title", datatype=DataType.VARCHAR, max_length=256)
    schema.add_field(field_name="intents_json", datatype=DataType.VARCHAR, max_length=1024)
    schema.add_field(field_name="categories_json", datatype=DataType.VARCHAR, max_length=1024)
    schema.add_field(field_name="related_policy_ids_json", datatype=DataType.VARCHAR, max_length=1024)
    schema.add_field(field_name="source_uri", datatype=DataType.VARCHAR, max_length=2048)
    schema.add_field(field_name="source_path", datatype=DataType.VARCHAR, max_length=512)
    schema.add_field(field_name="source_file_sha256", datatype=DataType.VARCHAR, max_length=64)
    schema.add_field(field_name="content_sha256", datatype=DataType.VARCHAR, max_length=64)
    schema.add_field(field_name="content", datatype=DataType.VARCHAR, max_length=4096)
    return schema


def ensure_collection(client: MilvusClient, name: str) -> bool:
    """Create the dev collection if absent; never drop or alter an existing collection."""
    if client.has_collection(collection_name=name):
        description = client.describe_collection(collection_name=name)
        fields = {field.get("name") for field in description.get("fields", [])}
        required = {
            "chunk_id", VECTOR_FIELD, "document_id", "policy_version", "content",
            "environment_scope", "locale", "jurisdiction", "synthetic_demo",
        }
        if not required.issubset(fields):
            raise RuntimeError(f"Existing collection {name!r} does not match the expected Day 3 schema; refusing to modify it")
        return False
    index_params = client.prepare_index_params()
    index_params.add_index(field_name=VECTOR_FIELD, index_type="AUTOINDEX", metric_type="COSINE")
    client.create_collection(collection_name=name, schema=_schema(client), index_params=index_params)
    return True


def _embedding_text(chunk: dict[str, Any]) -> str:
    # Keep semantic vectors focused on the passage. Titles/intents stay in scalar
    # metadata and the separate TF-IDF baseline; adding them here blurred section matches.
    return str(chunk["content"])


def _validate_dev_chunks(chunks: list[dict[str, Any]]) -> None:
    if not chunks:
        raise ValueError("No policy chunks were generated")
    for chunk in chunks:
        if (
            chunk.get("environment_scope") != "development-only"
            or chunk.get("status") != "draft"
            or chunk.get("synthetic_demo") is not True
        ):
            raise ValueError(f"Refusing to index non-demo or non-draft chunk {chunk.get('chunk_id')}")


def index_policy_chunks(
    chunks: list[dict[str, Any]] | None = None,
    *,
    client: MilvusClient | None = None,
    model_name: str | None = None,
) -> dict[str, Any]:
    owned_client = client is None
    client = client or create_client()
    collection = collection_name()
    chunks = chunks or build_policy_chunks()
    _validate_dev_chunks(chunks)
    write_policy_chunks(chunks)
    try:
        created = ensure_collection(client, collection)
        vectors = encode_texts([_embedding_text(row) for row in chunks], model_name=model_name)
        if len(vectors) != len(chunks) or any(len(vector) != VECTOR_DIMENSION for vector in vectors):
            raise RuntimeError("Embedding model output dimension does not match the Milvus collection")
        entities = []
        for chunk, vector in zip(chunks, vectors):
            entity = {key: chunk[key] for key in OUTPUT_FIELDS}
            entity[VECTOR_FIELD] = vector
            entities.append(entity)
        result = client.upsert(collection_name=collection, data=entities)
        client.load_collection(collection_name=collection)
        return {
            "collection": collection,
            "collection_created": created,
            "chunk_count": len(chunks),
            "document_count": len({row["document_id"] for row in chunks}),
            "embedding_model": model_name or os.getenv("EMBEDDING_MODEL", DEFAULT_MODEL),
            "embedding_dimension": VECTOR_DIMENSION,
            "milvus_upsert_result": result,
            "writes_scoped_to": "synthetic draft documents / development-only",
        }
    finally:
        if owned_client:
            client.close()


if __name__ == "__main__":
    chunks = build_policy_chunks()
    result = index_policy_chunks(chunks)
    print(f"Indexed {result['chunk_count']} chunks from {result['document_count']} documents into {result['collection']}.")
    print(f"Scope: {result['writes_scoped_to']}; embedding dimension: {result['embedding_dimension']}.")
