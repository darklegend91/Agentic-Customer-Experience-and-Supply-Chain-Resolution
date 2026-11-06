"""Local sentence-transformer embedding loader used by the dev RAG baseline."""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from huggingface_hub import constants, snapshot_download
from sentence_transformers import SentenceTransformer


DEFAULT_MODEL = "sentence-transformers/all-MiniLM-L6-v2"


@lru_cache(maxsize=2)
def load_embedding_model(model_name: str | None = None) -> SentenceTransformer:
    """Load from the local cache with fallback to DEFAULT_MODEL."""
    candidates: list[str] = []
    if model_name:
        candidates.append(model_name)
    env_model = os.getenv("EMBEDDING_MODEL")
    if env_model and env_model not in candidates:
        candidates.append(env_model)
    if DEFAULT_MODEL not in candidates:
        candidates.append(DEFAULT_MODEL)

    for candidate in candidates:
        local_path = Path(candidate).expanduser()
        if local_path.exists():
            return SentenceTransformer(str(local_path.resolve()), local_files_only=True, trust_remote_code=False)
        repo_cache = Path(constants.HF_HUB_CACHE) / f"models--{candidate.replace('/', '--')}"
        ref_file = repo_cache / "refs" / "main"
        snapshot = repo_cache / "snapshots" / ref_file.read_text(encoding="utf-8").strip() if ref_file.exists() else None
        if snapshot is not None and (snapshot / "modules.json").is_file() and (snapshot / "config.json").is_file():
            return SentenceTransformer(str(snapshot), local_files_only=True, trust_remote_code=False)
        try:
            model_path = snapshot_download(repo_id=candidate, local_files_only=True)
            return SentenceTransformer(model_path, local_files_only=True, trust_remote_code=False)
        except Exception:
            continue

    # If none found locally, try downloading online
    model_path = snapshot_download(repo_id=candidates[0], local_files_only=False)
    return SentenceTransformer(model_path, local_files_only=True, trust_remote_code=False)


def encode_texts(texts: list[str], model_name: str | None = None) -> list[list[float]]:
    if not texts:
        return []
    model = load_embedding_model(model_name)
    vectors = model.encode(
        texts,
        batch_size=32,
        normalize_embeddings=True,
        convert_to_numpy=True,
        show_progress_bar=False,
    )
    return vectors.astype("float32").tolist()
