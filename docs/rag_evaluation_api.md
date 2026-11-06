# RAG Evaluation API

This is a local development API for inspecting retrieved evidence and evaluating the labeled synthetic policy set. It searches the read-only development collection and never writes to Milvus.

## Start the API

From the workspace root, install the project dependencies if needed, create the versioned chunks, and index them once into the development collection:

```bash
./.venv/bin/python -m pip install -r requirements.txt
./.venv/bin/python scripts/chunk_versioned_policies.py
EMBEDDING_MODEL=sentence-transformers/all-MiniLM-L6-v2 ./.venv/bin/python scripts/index_dev_policies.py
EMBEDDING_MODEL=sentence-transformers/all-MiniLM-L6-v2 ./.venv/bin/python -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000
```

Keep the server bound to `127.0.0.1`. The evaluation API has no user authentication and is intended for local development. The embedding override selects the cached model used to build the Milvus collection. Set `MILVUS_URI`, `MILVUS_TOKEN`, and optionally `MILVUS_COLLECTION=agentic_customer_support_dev_policies_v1` in the ignored local `.env`.

Open [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs) to try the endpoints through Swagger UI. `/health` checks that the API process is up; it does not check Milvus connectivity.

## Evaluate one query

Use `POST /rag/evaluate`. Include the known answer labels to get hit scores; omit them for evidence inspection only.

```json
{
  "query": "What should support do when the applicable policy version is missing?",
  "expected_document_id": "DEMO-EVIDENCE-GAPS",
  "expected_policy_version": "1.0.0",
  "expected_section_title": "Applicable policy version missing",
  "top_k": 3,
  "methods": ["semantic", "keyword"]
}
```

The response contains results for each selected method. Each hit includes `document_id`, `policy_version`, section, chunk ID, score, source hash, and the excerpt. Per-query evaluation flags whether the expected document, version, and section appeared at rank 1 and whether the expected document appeared within the requested top K.

Equivalent command-line request:

```bash
curl -sS -X POST http://127.0.0.1:8000/rag/evaluate \
  -H 'Content-Type: application/json' \
  -d '{"query":"What should support do when the applicable policy version is missing?","expected_document_id":"DEMO-EVIDENCE-GAPS","expected_policy_version":"1.0.0","expected_section_title":"Applicable policy version missing","top_k":3,"methods":["semantic","keyword"]}'
```

## Run the full labeled set

Use `POST /rag/evaluate/labeled-set` with `{"top_k":3,"methods":["semantic","keyword"]}`. If `cases` is omitted, the endpoint reads the 11 cases in `data/processed/rag_policy_evaluation_v1.csv`, including the damaged-item question. The response includes per-method Hit@1, Hit@K, MRR@K, section/version accuracy, scope compliance, citation completeness, and each case's returned excerpts.

`Hit@K` means the expected document ID appears anywhere in the first K results. MRR@K rewards placing that document nearer the top. Version and section scores require the expected document to be at rank 1 as well. For this small synthetic set, use these numbers to compare code changes; they are not evidence of production policy accuracy.

## Errors

- `422`: request is invalid, such as a blank query or `top_k` outside 1–10.
- `503`: the chunk file, Milvus collection, credentials, or local embedding model is unavailable. Check the environment and run the chunk/index steps.
- An empty `hits` list means no passage matched the requested development marketplace filter. It is not a policy conclusion.
