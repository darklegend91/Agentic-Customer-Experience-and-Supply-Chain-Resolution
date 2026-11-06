Day 3 Sprint – Production‑Ready Classification + RAG Baseline

Goal: 
End‑to‑end ticket triage that 
(1) classifies incoming tickets, 
(2) retrieves relevant policy / knowledge‑base chunks
(3) evaluates the whole pipeline.

Below is a step‑by‑step guide that follows the folder layout already used in the repository (see Project_5.docx for the high‑level sprint plan). All commands assume you are in the project root:

/Users/adityapathania/Codes/bz/Agentic_Customer_Experience_Supply_Chain_Resolution

1️⃣ Architecture Overview

┌─────────────────────┐          ┌─────────────────────┐
│   Ticket Service    │  POST →  │   FastAPI / Flask   │
│  (front‑end UI)     │          │   ticket‑router     │
└─────────────────────┘          └─────────────────────┘
           │                               │
           ▼                               ▼
   ┌─────────────────┐            ┌─────────────────┐
   │  Classification │            │   RAG Engine    │
   │  (LLM / XGBoost)│            │  (Chunking →   │
   └─────────────────┘            │  Embedding →   │
            │                     │  Milvus)       │
            ▼                     └─────────────────┘
   ┌─────────────────┐                    │
   │  Neo4j / Neon  │ ◀───────►  Vector DB (Milvus) │
   │  Relational DB │   Store IDs & meta          │
   └─────────────────┘                    ▼
                                   ┌─────────────────┐
                                   │   Evaluation    │
                                   │ (Metrics, UI)   │
                                   └─────────────────┘

Classification – lightweight model (e.g., distilbert-base-uncased-finetuned-sst-2) or a fine‑tuned XGBoost on TF‑IDF vectors.
Chunking & Embedding – split policy & knowledge PDFs/Docs → 500‑token chunks → embed with a Sentence‑Transformer (all‑mpnet‑base‑v2).
Vector Store – Milvus (serverless on Neon‑Object‑Storage or self‑hosted) for ANN search.
Metadata – Neon PostgreSQL holds ticket metadata, classification label, and Milvus vector_id foreign‑key.
Evaluation – a labelled CSV (evaluation_set.csv) with ticket_id,expected_label,expected_doc_ids. Compute accuracy, macro‑F1, Recall@k for retrieval.

2️⃣ Folder Structure (Day 3 additions)
project_root/
├─ data/
│   ├─ tickets/                # raw ticket JSON/CSV
│   ├─ policy_documents/       # PDFs, DOCX, markdown
│   ├─ evaluation_set.csv      # labelled test set for triage
│   └─ embeddings/             # optional cached embeddings (npz)
├─ src/
│   ├─ classification/
│   │   ├─ train_classifier.py
│   │   ├─ infer_classifier.py
│   │   └─ utils.py
│   ├─ rag/
│   │   ├─ chunker.py
│   │   ├─ embedder.py
│   │   ├─ milvus_client.py
│   │   └─ retrieve.py
│   ├─ api/
│   │   ├─ main.py            # FastAPI entry‑point
│   │   └─ routes.py
│   └─ eval/
│       ├─ eval_metrics.py
│       └─ eval_report.py
├─ scripts/
│   ├─ ingest_documents.sh      # runs chunker + embedder → Milvus
│   ├─ load_evaluation_set.sh   # import CSV to Neon
│   └─ deploy.sh                # docker‑compose / helm wrapper
├─ tests/
│   ├─ test_classification.py
│   ├─ test_rag.py
│   └─ test_api.py
├─ Dockerfile
├─ docker-compose.yml
├─ requirements.txt
└─ README.md

All new code lives under src/ – keep it import‑friendly (src is added to PYTHONPATH in Dockerfile).

3️⃣ Prerequisites
Tool	Install Command	Why
Python 3.14 (already in .venv)	python -m venv .venv && source .venv/bin/activate	Base runtime
Poetry / pip-tools	pip install poetry	Pin‑exact dependencies
FastAPI & uvicorn	poetry add fastapi uvicorn	HTTP API
scikit‑learn / xgboost	poetry add scikit-learn xgboost	Classification models
sentence‑transformers	poetry add sentence-transformers	Embeddings
Milvus‑client	poetry add pymilvus	Vector DB
python‑docx & PyPDF2	poetry add python-docx PyPDF2	Document extraction
psycopg2‑binary	poetry add psycopg2-binary	Neon DB driver
tiktoken (optional)	poetry add tiktoken	token‑aware chunking
Docker	install from Docker.com	Containerisation
Neon CLI (optional)	brew install neonctl	Manage Neon branches

All secrets (Neon DATABASE_URL, Milvus endpoint, LLM API keys) stay in .env (already in repo). Add the missing keys:

dotenv
# .env (append)
MILVUS_ENDPOINT=milvus://<host>:19530
MILVUS_TOKEN=your‑milvus‑token
LLM_API_KEY=…               # e.g. Anthropic / OpenAI
EMBEDDING_MODEL=all-mpnet-base-v2
4️⃣ Implementation Details
4.1 Document Ingestion (Chunk → Embed → Store)

src/rag/chunker.py

python
import pathlib, itertools, re
from typing import List, Tuple
import tiktoken  # optional, fallback to split on punctuation
TOKENIZER = tiktoken.get_encoding("cl100k_base")
CHUNK_SIZE = 500            # tokens
OVERLAP = 50                # tokens
def _token_len(text: str) -> int:
    return len(TOKENIZER.encode(text))
def split_text(text: str) -> List[str]:
    """Recursive split on punctuation until each segment ≤ CHUNK_SIZE tokens."""
    if _token_len(text) <= CHUNK_SIZE:
        return [text.strip()]
    # try splitting on sentences first
    parts = re.split(r'(?<=[.!?])\s+', text)
    # if still too big, split on commas etc.
    if any(_token_len(p) > CHUNK_SIZE for p in parts):
        parts = re.split(r'[,\n]', text)
    chunks = []
    buffer = ""
    for p in parts:
        candidate = f"{buffer} {p}".strip()
        if _token_len(candidate) <= CHUNK_SIZE:
            buffer = candidate
        else:
            if buffer:
                chunks.append(buffer)
            buffer = p
    if buffer:
        chunks.append(buffer)
    # add overlap windows
    overlapped = []
    for i, chunk in enumerate(chunks):
        overlapped.append(chunk)
        if i + 1 < len(chunks):
            # create a sliding window with `OVERLAP` tokens from the end
            tail = " ".join(chunks[i + 1].split()[:OVERLAP])
            overlapped.append(f"{chunk} {tail}")
    return overlapped

src/rag/embedder.py

python
from sentence_transformers import SentenceTransformer
import numpy as np
MODEL = SentenceTransformer("all-mpnet-base-v2")  # cached on first run
def embed_chunks(chunks: List[str]) -> np.ndarray:
    """Return (n_chunks, dim) float32 array."""
    return MODEL.encode(chunks, batch_size=64, normalize_embeddings=True).astype("float32")

src/rag/milvus_client.py

python
from pymilvus import Collection, FieldSchema, CollectionSchema, DataType, connections
import numpy as np
from pathlib import Path
def init_milvus(collection_name: str = "policy_chunks", dim: int = 768):
    connections.connect(alias="default", host="milvus", port="19530")  # env var overrides possible
    if Collection.exists(collection_name):
        return Collection(name=collection_name)
    fields = [
        FieldSchema(name="pk", dtype=DataType.INT64, is_primary=True, auto_id=True),
        FieldSchema(name="vector", dtype=DataType.FLOAT_VECTOR, dim=dim),
        FieldSchema(name="text", dtype=DataType.VARCHAR, max_length=65535),
        FieldSchema(name="source_file", dtype=DataType.VARCHAR, max_length=256),
        FieldSchema(name="chunk_idx", dtype=DataType.INT64),
    ]
    schema = CollectionSchema(fields, "Policy doc chunks")
    coll = Collection(name=collection_name, schema=schema)
    coll.create_index(field_name="vector", index_params={"metric_type":"IP","index_type":"IVF_FLAT","params":{"nlist":1024}})
    coll.load()
    return coll
def upsert_chunks(collection: Collection, vectors: np.ndarray, texts: List[str],
                 source_file: str):
    ids = list(range(collection.num_entities, collection.num_entities + len(texts)))
    data = [
        ids,
        vectors.tolist(),
        texts,
        [source_file] * len(texts),
        list(range(len(texts)))   # chunk_idx
    ]
    collection.insert(data)
    collection.flush()

scripts/ingest_documents.sh

bash
#!/usr/bin/env bash
set -euo pipefail
PROJECT_ROOT=$(git rev-parse --show-toplevel)
SRC=$PROJECT_ROOT/src/rag
# 1️⃣  Extract raw text from PDFs/DOCX
python - <<PY
import pathlib, json, sys
from src.rag.chunker import split_text
from src.rag.embedder import embed_chunks
from src.rag.milvus_client import init_milvus, upsert_chunks
from PyPDF2 import PdfReader
import docx
DATA_DIR = pathlib.Path("$PROJECT_ROOT/data/policy_documents")
COLL = init_milvus()
for file in DATA_DIR.glob("*.*"):
    if file.suffix.lower() == ".pdf":
        text = "\n".join(page.extract_text() for page in PdfReader(str(file)).pages)
    elif file.suffix.lower() in {".docx", ".doc"}:
        doc = docx.Document(str(file))
        text = "\n".join(p.text for p in doc.paragraphs)
    else:
        continue
    chunks = split_text(text)
    vectors = embed_chunks(chunks)
    upsert_chunks(COLL, vectors, chunks, source_file=file.name)
    print(f"✅ {file.name} → {len(chunks)} chunks")
PY

Run once:

bash
chmod +x scripts/ingest_documents.sh
./scripts/ingest_documents.sh

Scalability tip: Replace the single‑process loop with Ray / Dask for parallel chunk‑encode on large corpora. Milvus handles horizontal scaling automatically (add more query nodes, enable sharding).

4.2 Ticket Classification

src/classification/train_classifier.py

python
import pandas as pd
from sklearn.model_selection import train_test_split
from sklearn.feature_extraction.text import TfidfVectorizer
from xgboost import XGBClassifier
import joblib, os
DATA_PATH = os.getenv("TICKETS_CSV", "data/tickets/tickets.csv")
df = pd.read_csv(DATA_PATH)                     # columns: ticket_id, text, label
X_train, X_test, y_train, y_test = train_test_split(
    df["text"], df["label"], test_size=0.2, random_state=42, stratify=df["label"]
)
tfidf = TfidfVectorizer(max_features=10_000, ngram_range=(1, 2))
Xtr = tfidf.fit_transform(X_train)
Xte = tfidf.transform(X_test)
clf = XGBClassifier(
    n_estimators=200,
    max_depth=6,
    learning_rate=0.1,
    objective="multi:softprob",
    eval_metric="mlogloss",
    subsample=0.8,
    colsample_bytree=0.8,
    tree_method="hist",
)
clf.fit(Xtr, y_train)
# Save artefacts for inference
os.makedirs("models/classifier", exist_ok=True)
joblib.dump(tfidf, "models/classifier/tfidf.pkl")
joblib.dump(clf, "models/classifier/xgb.pkl")
print("✅ Model trained – artefacts written to models/classifier/")

src/classification/infer_classifier.py

python
import joblib, os
from fastapi import HTTPException
tfidf = joblib.load("models/classifier/tfidf.pkl")
clf   = joblib.load("models/classifier/xgb.pkl")
def predict_label(text: str) -> str:
    vec = tfidf.transform([text])
    probs = clf.predict_proba(vec)[0]
    idx = probs.argmax()
    label = clf.classes_[idx]
    return label

The classifier is lightweight (≈ 5 MB) and can be hot‑reloaded inside the API container.

4.3 Retrieval Engine

src/rag/retrieve.py

python
from pymilvus import Collection, connections
import numpy as np
from sentence_transformers import SentenceTransformer
MODEL = SentenceTransformer(os.getenv("EMBEDDING_MODEL", "all-mpnet-base-v2"))
COLL = Collection(name="policy_chunks")   # already loaded in milvus_client.init_milvus()
def retrieve(query: str, top_k: int = 5) -> list[dict]:
    q_vec = MODEL.encode([query], normalize_embeddings=True).astype("float32")
    search_params = {"metric_type": "IP", "params": {"nprobe": 10}}
    results = COLL.search(
        data=q_vec,
        anns_field="vector",
        param=search_params,
        limit=top_k,
        expr=None,
        output_fields=["text", "source_file", "chunk_idx"],
    )
    hits = []
    for hits_batch in results:
        for hit in hits_batch:
            hits.append(
                {
                    "score": hit.distance,
                    "text": hit.entity.get("text"),
                    "source_file": hit.entity.get("source_file"),
                    "chunk_idx": hit.entity.get("chunk_idx"),
                }
            )
    return hits
4.4 API End‑to‑End Endpoint

src/api/main.py

python
import os
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from classification.infer_classifier import predict_label
from rag.retrieve import retrieve
import psycopg2, json
app = FastAPI(title="Ticket‑Triage RAG API")
class TicketIn(BaseModel):
    ticket_id: str
    text: str
class TicketOut(BaseModel):
    ticket_id: str
    label: str
    retrieved: list[dict]
def _store_ticket(ticket_id: str, label: str, retrieved: list[dict]):
    conn = psycopg2.connect(os.getenv("DATABASE_URL"), sslmode="require")
    cur = conn.cursor()
    # Store ticket + classification + vector ids (as JSON)
    cur.execute(
        """
        INSERT INTO tickets (ticket_id, raw_text, label, retrieved_chunks)
        VALUES (%s, %s, %s, %s)
        ON CONFLICT (ticket_id) DO UPDATE
        SET label = EXCLUDED.label,
            retrieved_chunks = EXCLUDED.retrieved_chunks;
        """,
        (ticket_id, json.dumps(retrieved), label, json.dumps(retrieved)),
    )
    conn.commit()
    cur.close()
    conn.close()
@app.post("/triage", response_model=TicketOut)
def triage(ticket: TicketIn):
    label = predict_label(ticket.text)
    chunks = retrieve(ticket.text, top_k=5)
    _store_ticket(ticket.ticket_id, label, chunks)
    return TicketOut(ticket_id=ticket.ticket_id, label=label, retrieved=chunks)

Add a tickets table in Neon (run once):

sql
CREATE TABLE IF NOT EXISTS tickets (
    ticket_id TEXT PRIMARY KEY,
    raw_text TEXT,
    label TEXT,
    retrieved_chunks JSONB,
    created_at TIMESTAMPTZ DEFAULT now()
);

You can embed this in a migration script (data/create_tables.sql) and run via psql "$DATABASE_URL" -f data/create_tables.sql.

5️⃣ Evaluation Set & Metrics
Create evaluation_set.csv (inside data/). Columns:
ticket_id,expected_label,expected_doc_ids   # doc ids are Milvus PKs (comma‑separated)
Evaluation script

src/eval/eval_metrics.py

python
import pandas as pd, json, psycopg2, os
from sklearn.metrics import accuracy_score, f1_score, classification_report
def load_predictions():
    conn = psycopg2.connect(os.getenv("DATABASE_URL"), sslmode="require")
    cur = conn.cursor()
    cur.execute("SELECT ticket_id, label, retrieved_chunks FROM tickets")
    rows = cur.fetchall()
    cur.close()
    conn.close()
    preds = pd.DataFrame(rows, columns=["ticket_id", "pred_label", "retrieved"])
    preds["retrieved_ids"] = preds["retrieved"].apply(
        lambda j: [c["id"] for c in json.loads(j)] if j else []
    )
    return preds
def evaluate():
    eval_df = pd.read_csv("data/evaluation_set.csv")
    preds = load_predictions()
    merged = eval_df.merge(preds, on="ticket_id", how="inner")
    # Classification accuracy
    acc = accuracy_score(merged["expected_label"], merged["pred_label"])
    f1 = f1_score(merged["expected_label"], merged["pred_label"], average="macro")
    # Retrieval Recall@k (k=5)
    def recall(row):
        expected = set(map(int, row["expected_doc_ids"].split(",")))
        retrieved = set(row["retrieved_ids"])
        return len(expected & retrieved) / len(expected)
    merged["recall@5"] = merged.apply(recall, axis=1)
    recall_mean = merged["recall@5"].mean()
    print(f"Classification – Acc: {acc:.3f}, Macro‑F1: {f1:.3f}")
    print(f"Retrieval – Recall@5: {recall_mean:.3f}")
if __name__ == "__main__":
    evaluate()

Run after the API has processed the whole evaluation set (e.g., via a bulk POST script).

6️⃣ Production‑Ready Packaging
Dockerfile (single image)
dockerfile
FROM python:3.14-slim
# System deps
RUN apt-get update && apt-get install -y gcc libpq-dev && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY pyproject.toml poetry.lock ./
RUN pip install poetry && poetry config virtualenvs.create false && poetry install --no-dev
COPY . .
ENV PYTHONPATH=/app/src
EXPOSE 8000
CMD ["uvicorn", "src.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
docker‑compose.yml (Neon proxy & Milvus)
yaml
version: "3.8"
services:
  api:
    build: .
    env_file: .env
    ports: ["8000:8000"]
    depends_on: [milvus]
  milvus:
    image: milvusdb/milvus:2.3.0
    container_name: milvus
    environment:
      - MILVUS_LOG_LEVEL=info
    ports: ["19530:19530"]
    volumes:
      - milvus-storage:/var/lib/milvus
volumes:
  milvus-storage:

Deploy with:

bash
docker compose up -d

Scaling notes

Component	How to scale
FastAPI	Increase replicas in Docker Swarm / Kubernetes (replicas: 3), use a load balancer (NGINX or Cloud‑LB).
Milvus	Add more query nodes (milvus-standalone → milvus-distributed), enable sharding (partition_num).
Neon	Serverless – auto‑scales. For heavy write bursts, use the unpooled connection (DATABASE_URL_UNPOOLED).
Embedding model	Cache embeddings on disk (embeddings/) and reuse; for massive corpora, pre‑compute offline with Ray.
7️⃣ CI / Testing

Add a GitHub Actions workflow (.github/workflows/ci.yml) that:

Spins up Docker Compose (docker compose up -d).
Runs unit tests (pytest -q tests/).
Executes scripts/ingest_documents.sh on a small fixture set.
Fires the evaluation script and fails if Recall@5 < 0.7 or Accuracy < 0.8.
yaml
name: CI
on: [push, pull_request]
jobs:
  test:
    runs-on: ubuntu-latest
    services:
      postgres:
        image: postgres:15
        env:
          POSTGRES_PASSWORD: postgres
          POSTGRES_DB: testdb
        ports: ["5432:5432"]
    steps:
      - uses: actions/checkout@v4
      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.14"
      - name: Install Poetry
        run: pip install poetry
      - name: Install deps
        run: poetry install
      - name: Run tests
        run: pytest -q

All tests should be placed under tests/ and cover:

classifier training / inference (test_classification.py)
chunker edge cases (test_rag.py)
API health & response schema (test_api.py)
8️⃣ Checklist for Day 3 Completion
✅	Item
1	Document ingestion – scripts/ingest_documents.sh executed, Milvus populated.
2	Classification model – train_classifier.py run, artefacts in models/classifier/.
3	FastAPI service – reachable at http://localhost:8000/triage.
4	Neon table tickets created (run the migration).
5	Evaluation CSV uploaded, load_evaluation_set.sh imported to Neon.
6	Evaluation script eval_metrics.py produces > 0.8 accuracy and > 0.7 Recall@5.
7	Docker compose runs both API and Milvus, passes CI tests.
8	Documentation – update README.md with start‑up commands, environment variables, and scaling hints.
9️⃣ Next Steps (Day 4+)
Add LLM‑based re‑ranking – after Milvus retrieval, run a small Claude/ChatGPT prompt to score relevance.
Feedback loop – store user‑confirmed classifications to continuously fine‑tune the XGBoost model.
Observability – export metrics to Prometheus (FastAPI metrics endpoint) and set alerts on latency > 300 ms.
RBAC & Auditing – use Neon role‑based permissions and Milvus auth tokens for production security.

Feel free to ask for any specific code files or deeper dive into a particular component (e.g., Milvus sharding config, CI pipelines, or LLM routing). Happy building! 🚀