FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HF_HOME=/opt/model-cache \
    HF_HUB_CACHE=/opt/model-cache/hub \
    HF_HUB_OFFLINE=1 \
    TRANSFORMERS_OFFLINE=1 \
    EMBEDDING_MODEL=sentence-transformers/all-MiniLM-L6-v2

WORKDIR /app

RUN apt-get update \
    && apt-get install --no-install-recommends -y ca-certificates libgomp1 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./requirements.txt
RUN python -m pip install --no-cache-dir --upgrade pip \
    && python -m pip install --no-cache-dir -r requirements.txt

COPY backend/ ./backend/
COPY frontend/ ./frontend/
COPY scripts/ ./scripts/
COPY deploy/start.sh ./deploy/start.sh
COPY knowledge_base/ ./knowledge_base/
COPY data/processed/ ./data/processed/

# Build the synthetic demo artifacts into the image. Runtime containers do not
# need to train or download models, and do not receive raw fixture exports.
RUN python scripts/train_classifier.py \
    && python scripts/chunk_versioned_policies.py \
    && HF_HUB_OFFLINE=0 TRANSFORMERS_OFFLINE=0 python - <<'PY'
from huggingface_hub import snapshot_download

snapshot_download(
    repo_id="sentence-transformers/all-MiniLM-L6-v2",
    cache_dir="/opt/model-cache/hub",
)
PY

RUN useradd --create-home --uid 10001 appuser \
    && chown -R appuser:appuser /app /opt/model-cache

USER appuser

EXPOSE 8000 8501

CMD ["sh", "/app/deploy/start.sh", "all"]
