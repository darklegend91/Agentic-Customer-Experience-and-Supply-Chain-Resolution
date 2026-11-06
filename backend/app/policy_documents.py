"""Chunk versioned policy, FAQ, and escalation source files with citations."""

from __future__ import annotations

import csv
import hashlib
import json
import re
from pathlib import Path
from typing import Any

import yaml


PROJECT_ROOT = Path(__file__).resolve().parents[2]
KNOWLEDGE_BASE = PROJECT_ROOT / "knowledge_base"
OUTPUT_DIR = PROJECT_ROOT / "data" / "processed"
CHUNK_SIZE = 1000
CHUNK_OVERLAP = 120

CHUNK_COLUMNS = [
    "chunk_id", "document_id", "policy_id", "policy_version", "artifact_type", "title",
    "status", "marketplace", "jurisdiction", "environment_scope", "synthetic_demo", "locale",
    "effective_from", "effective_to", "section_id", "section_title", "intents_json",
    "categories_json", "related_policy_ids_json", "source_uri", "source_path",
    "source_file_sha256", "content_sha256", "content",
]


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _split_frontmatter(text: str, path: Path) -> tuple[dict[str, Any], str]:
    match = re.match(r"\A---\s*\n(.*?)\n---\s*\n(.*)\Z", text, flags=re.DOTALL)
    if not match:
        raise ValueError(f"Missing YAML frontmatter: {path}")
    metadata = yaml.safe_load(match.group(1)) or {}
    body = match.group(2).strip()
    if not isinstance(metadata, dict):
        raise ValueError(f"Frontmatter must be a YAML mapping: {path}")
    return metadata, body


def _document_identity(metadata: dict[str, Any], path: Path) -> tuple[str, str]:
    document_id = metadata.get("policy_id") or metadata.get("faq_id") or metadata.get("rule_id")
    if not document_id or not metadata.get("version"):
        raise ValueError(f"Document ID and version are required: {path}")
    return str(document_id), str(metadata["version"])


def _section_blocks(body: str) -> list[tuple[str, str]]:
    headings = list(re.finditer(r"(?m)^#{1,6}\s+(.+?)\s*$", body))
    if not headings:
        return [("content", body.strip())] if body.strip() else []
    sections: list[tuple[str, str]] = []
    if body[:headings[0].start()].strip():
        sections.append(("Introduction", body[:headings[0].start()].strip()))
    for index, heading in enumerate(headings):
        start = heading.end()
        end = headings[index + 1].start() if index + 1 < len(headings) else len(body)
        title = heading.group(1).strip()
        text = body[start:end].strip()
        if text:
            sections.append((title, text))
    return sections


def _split_text(text: str, max_chars: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> list[str]:
    normalized = re.sub(r"[ \t]+", " ", text).strip()
    if not normalized:
        return []
    chunks: list[str] = []
    start = 0
    while start < len(normalized):
        end = min(start + max_chars, len(normalized))
        if end < len(normalized):
            candidates = [normalized.rfind("\n", start, end), normalized.rfind(". ", start, end), normalized.rfind("; ", start, end), normalized.rfind(" ", start, end)]
            boundary = max(candidates)
            if boundary > start + int(max_chars * 0.55):
                end = boundary + (1 if normalized[boundary:boundary + 1] == "\n" else 0)
        piece = normalized[start:end].strip()
        if piece:
            chunks.append(piece)
        if end >= len(normalized):
            break
        start = max(end - overlap, start + 1)
    return chunks


def _make_row(
    *, metadata: dict[str, Any], document_id: str, version: str, artifact_type: str,
    title: str, section_id: str, section_title: str, content: str, source_path: Path,
    source_hash: str, chunk_index: int,
) -> dict[str, Any]:
    policy_id = str(metadata.get("policy_id") or "")
    related = metadata.get("linked_policy_ids") or ([policy_id] if policy_id else [])
    chunk_identity = f"{document_id}|{version}|{section_id}|{chunk_index}"
    return {
        "chunk_id": "pol-" + hashlib.sha256(chunk_identity.encode("utf-8")).hexdigest()[:32],
        "document_id": document_id,
        "policy_id": policy_id,
        "policy_version": version,
        "artifact_type": artifact_type,
        "title": title,
        "status": str(metadata.get("status") or ""),
        "marketplace": str(metadata.get("marketplace") or ""),
        "jurisdiction": str(metadata.get("jurisdiction") or ""),
        "environment_scope": str(metadata.get("environment_scope") or ""),
        "synthetic_demo": bool(metadata.get("synthetic_demo", False)),
        "locale": str(metadata.get("locale") or ""),
        "effective_from": str(metadata.get("effective_from") or ""),
        "effective_to": str(metadata.get("effective_to") or ""),
        "section_id": section_id,
        "section_title": section_title,
        "intents_json": json.dumps(metadata.get("intents", []), ensure_ascii=False),
        "categories_json": json.dumps(metadata.get("categories", []), ensure_ascii=False),
        "related_policy_ids_json": json.dumps(related, ensure_ascii=False),
        "source_uri": str(metadata.get("source_uri") or ""),
        "source_path": str(source_path.relative_to(PROJECT_ROOT)),
        "source_file_sha256": source_hash,
        # This is a locally computed source-file checksum, not an approval hash.
        "content_sha256": str(metadata.get("content_sha256") or ""),
        "content": content,
    }


def _load_markdown(path: Path) -> list[dict[str, Any]]:
    text = path.read_text(encoding="utf-8")
    metadata, body = _split_frontmatter(text, path)
    document_id, version = _document_identity(metadata, path)
    if metadata.get("environment_scope") != "development-only" or metadata.get("synthetic_demo") is not True:
        raise ValueError(f"Only synthetic development-only documents are accepted by this build: {path}")
    if metadata.get("status") != "draft":
        raise ValueError(f"Expected a draft-only development knowledge base: {path}")
    artifact_type = {"policies": "policy", "faqs": "faq"}.get(path.parents[1].name, "policy")
    title = str(metadata.get("title") or metadata.get("faq_id") or document_id)
    source_hash = sha256_file(path)
    rows = []
    for section_number, (section_title, section_text) in enumerate(_section_blocks(body), start=1):
        section_id = f"S{section_number:02d}"
        for chunk_index, excerpt in enumerate(_split_text(section_text), start=1):
            rows.append(_make_row(
                metadata=metadata,
                document_id=document_id,
                version=version,
                artifact_type=artifact_type,
                title=title,
                section_id=section_id,
                section_title=section_title,
                content=excerpt,
                source_path=path,
                source_hash=source_hash,
                chunk_index=chunk_index,
            ))
    return rows


def _load_yaml_rule(path: Path) -> list[dict[str, Any]]:
    text = path.read_text(encoding="utf-8")
    metadata = yaml.safe_load(text) or {}
    if not isinstance(metadata, dict):
        raise ValueError(f"Escalation rule must be a YAML mapping: {path}")
    document_id, version = _document_identity(metadata, path)
    if metadata.get("environment_scope") != "development-only" or metadata.get("synthetic_demo") is not True:
        raise ValueError(f"Only synthetic development-only documents are accepted by this build: {path}")
    if metadata.get("status") != "draft":
        raise ValueError(f"Expected a draft-only development knowledge base: {path}")
    artifact_type = "escalation_rule"
    title = document_id
    source_hash = sha256_file(path)
    conditions = metadata.get("conditions") or []
    rows = []
    for section_number, condition in enumerate(conditions, start=1):
        when = str(condition.get("when") or "condition")
        action = str(condition.get("action") or "review")
        section_title = when.replace("_", " ").capitalize()
        excerpt = f"Condition: {when.replace('_', ' ')}. Required action: {action.replace('_', ' ')}."
        rows.append(_make_row(
            metadata=metadata,
            document_id=document_id,
            version=version,
            artifact_type=artifact_type,
            title=title,
            section_id=f"C{section_number:02d}",
            section_title=section_title,
            content=excerpt,
            source_path=path,
            source_hash=source_hash,
            chunk_index=1,
        ))
    return rows


def build_policy_chunks(knowledge_base: Path = KNOWLEDGE_BASE) -> list[dict[str, Any]]:
    """Build chunks only from the versioned Day 2 synthetic source files."""
    files = sorted(knowledge_base.glob("policies/*/*.md"))
    files += sorted(knowledge_base.glob("faqs/*/*.md"))
    files += sorted(knowledge_base.glob("escalation_rules/*/*.yaml"))
    if not files:
        raise FileNotFoundError(f"No versioned policy sources found under {knowledge_base}")
    chunks: list[dict[str, Any]] = []
    for path in files:
        if path.suffix.lower() == ".yaml":
            chunks.extend(_load_yaml_rule(path))
        else:
            chunks.extend(_load_markdown(path))
    ids = [row["chunk_id"] for row in chunks]
    if len(ids) != len(set(ids)):
        raise ValueError("Chunk IDs must be unique")
    return chunks


def write_policy_chunks(chunks: list[dict[str, Any]], output_dir: Path = OUTPUT_DIR) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    jsonl_path = output_dir / "policy_chunks_v1.jsonl"
    with jsonl_path.open("w", encoding="utf-8") as stream:
        for chunk in chunks:
            stream.write(json.dumps(chunk, ensure_ascii=False) + "\n")
    csv_path = output_dir / "policy_chunks_v1.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=CHUNK_COLUMNS)
        writer.writeheader()
        writer.writerows(chunks)
    return jsonl_path, csv_path


if __name__ == "__main__":
    built = build_policy_chunks()
    jsonl, csv_path = write_policy_chunks(built)
    print(f"Created {len(built)} versioned policy chunks from {len({row['document_id'] for row in built})} documents.")
    print(f"JSONL: {jsonl.relative_to(PROJECT_ROOT)}")
    print(f"CSV: {csv_path.relative_to(PROJECT_ROOT)}")
