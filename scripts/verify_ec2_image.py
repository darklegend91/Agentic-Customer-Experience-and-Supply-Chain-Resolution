"""Exercise the demo image offline without database credentials or network calls."""

from __future__ import annotations

import json
import math
import os
from pathlib import Path
import resource
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main() -> None:
    if os.getenv("HF_HUB_OFFLINE") != "1" or os.getenv("TRANSFORMERS_OFFLINE") != "1":
        raise RuntimeError("Run this check with offline model loading enabled")
    os.environ["APP_ENV"] = "local"
    os.environ["LANGFUSE_TRACING_ENABLED"] = "false"

    import torch
    from fastapi.testclient import TestClient

    from backend.app.classification.laya import classify_with_laya
    from backend.app.embeddings import encode_texts
    from backend.app.main import app

    if torch.version.cuda is not None:
        raise RuntimeError("The EC2 demo expects CPU-only PyTorch")

    started = time.monotonic()
    classification = classify_with_laya("My order arrived damaged")
    if classification.get("provider") != "laya" or classification.get("fallback_used"):
        raise RuntimeError("Laya did not complete offline inference")
    first_seconds = time.monotonic() - started

    started = time.monotonic()
    cached = classify_with_laya("My order arrived damaged")
    cache_seconds = time.monotonic() - started
    if cached != classification:
        raise RuntimeError("Repeated classification changed its cached result")

    vectors = encode_texts(["How long does a refund take?"])
    if len(vectors) != 1 or len(vectors[0]) != 384:
        raise RuntimeError("The embedding model returned the wrong vector dimension")
    norm = math.sqrt(sum(value * value for value in vectors[0]))
    if not math.isclose(norm, 1.0, abs_tol=1e-4):
        raise RuntimeError("The embedding vector is not normalized")

    # No lifespan context: the foreground check already loaded Laya. Avoid
    # starting an unrelated background warmup or any database-backed workflow.
    client = TestClient(app)
    try:
        response = client.get("/health")
        if response.status_code != 200 or response.json().get("status") != "ok":
            raise RuntimeError("FastAPI health failed")
        response = client.post("/tickets/classify", json={
            "schema_version": "1.0", "message": "My order arrived damaged",
        })
        api_classification = response.json().get("classification", {})
        if response.status_code != 200 or api_classification.get("classifier_provider") != "laya" or api_classification.get("fallback_used"):
            raise RuntimeError("The classification API did not use Laya")
    finally:
        client.close()

    peak = Path("/sys/fs/cgroup/memory.peak")
    print(json.dumps({
        "status": "ok",
        "torch": torch.__version__,
        "torch_threads": torch.get_num_threads(),
        "classifier_provider": classification["provider"],
        "fallback_used": classification.get("fallback_used", False),
        "intent": classification["candidate_intent"],
        "embedding_dimension": len(vectors[0]),
        "first_classification_seconds": round(first_seconds, 3),
        "cached_classification_seconds": round(cache_seconds, 6),
        "process_peak_rss_mib": round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024, 1),
        "container_peak_mib": round(int(peak.read_text()) / 1024**2, 1) if peak.exists() else None,
    }, indent=2))


if __name__ == "__main__":
    main()
