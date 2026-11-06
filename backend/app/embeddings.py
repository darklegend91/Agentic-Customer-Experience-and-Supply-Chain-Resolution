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
    """Load from the local cache only; model downloads are an explicit setup step."""
    resolved_name = model_name or os.getenv("EMBEDDING_MODEL", DEFAULT_MODEL)
    local_path = Path(resolved_name).expanduser()
    if local_path.exists():
        model_path = str(local_path.resolve())
    else:
        # Resolve the cached snapshot explicitly. Some Hub/library combinations
        # fail to discover an existing snapshot from the repository ID alone.
        repo_cache = Path(constants.HF_HUB_CACHE) / f"models--{resolved_name.replace('/', '--')}"
        ref_file = repo_cache / "refs" / "main"
        snapshot = repo_cache / "snapshots" / ref_file.read_text(encoding="utf-8").strip() if ref_file.exists() else None
        if snapshot is not None and (snapshot / "modules.json").is_file() and (snapshot / "config.json").is_file():
            model_path = str(snapshot)
        else:
            model_path = snapshot_download(repo_id=resolved_name, local_files_only=True)
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
