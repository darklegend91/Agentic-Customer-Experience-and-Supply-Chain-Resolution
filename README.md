# Agentic Customer Experience and Supply Chain Resolution

This project is a controlled support-assistant MVP. It investigates tickets using scoped operational evidence and approved policy sources, then proposes a response or resolution for a human to review. It does not execute refunds or other live commerce actions.

## Day 1 design

- [Requirements and decisions](docs/requirements.md)
- [Intent taxonomy](docs/intent_taxonomy.md)
- [Dataset and data plan](docs/dataset_and_licence_notes.md)
- [Policy schema and lifecycle](docs/policy_schema.md)
- [Ticket, evidence, tool, proposal, and audit contracts](docs/api_contract.md)
- [Security and access boundaries](docs/security_model.md)
- [Production-oriented architecture](docs/architecture.md)
- [Private demo deployment runbook](docs/deployment.md)

These documents follow the project tree in docs/Project_5.docx, Section 11. Treat this directory as the canonical project root. Keep source code, data, policy files, tests, and documentation under this directory.

## Production boundary

The records currently in data/raw/ are generated fictional fixtures. Use them only for development and evaluation. No production order system, ticket provider, identity provider, policy owner, or retention schedule has been approved yet. Do not point this project at a production database or load the fixture into a production branch.

For Neon, the design uses separate development, staging, and protected production environments. Runtime application traffic uses the pooled connection. Reviewed migrations use the direct connection and a separate migration identity. Secrets belong in the deployment secret manager; local environment files are ignored by Git.

For a private synthetic-data cloud demo, follow [the deployment runbook](docs/deployment.md). Docker Compose runs FastAPI, a persisted LangGraph worker, Streamlit, and a Caddy HTTPS proxy. This setup is not a production customer-support deployment.

## Delivery status

Day 1's requirements, taxonomy, data plan, policy schema, API contracts, security boundaries, and architecture are documented. Day 2 preparation now creates customer-scoped synthetic loyalty records, prior-contact summaries, and a customer/order-isolated classifier holdout. The local-only generator is `scripts/generate_support_context_fixtures.py`; `scripts/prepare_data.py` validates and cleans its outputs. These scripts do not connect to Neon or Milvus.

The files in `data/raw/` are fictional development/evaluation fixtures. Synthetic policy and FAQ documents under `knowledge_base/` are drafts scoped to development only. Day 3 provides semantic and keyword RAG plus a Laya/TF-IDF classifier comparison; Laya's reported score is not calibrated and automated routing remains disabled by default. The existing unversioned Milvus collection remains unchanged. Versioned synthetic policy passages use a separate development collection; refresh it after chunking policy changes, since the newly added loyalty policy is only in the local chunks until that index operation is run. Day 4 adds local read-only FastAPI and MCP investigation interfaces, including scoped customer loyalty and prior-contact lookup. Day 5 adds the LangGraph supervisor, five specialist stages, a typed evidence ledger, deterministic evidence gates, durable PostgreSQL checkpoints, and authenticated simulation-only approval flow. Follow [the Day 5 LangGraph workflow guide](docs/day5_langgraph_workflow.md) to configure it.

Before production use, the business and security owners still need to approve the requirements, data sources, identity/access design, policy owners and effective dates, retention, and operating targets. See [requirements.md](docs/requirements.md) for the open decisions.

## Run the project locally

Run these commands from this repository root, which is also the project root. The application follows the documented folders directly (`backend/`, `data/`, `docs/`, and so on); there is no nested `agentic_customer_support/` source folder. Use Python 3.11 or newer. The API expects a development Neon database, a Milvus development collection, and the `sentence-transformers/all-MiniLM-L6-v2` model to be available locally. It does not create database tables or index policies when the API starts.

Create a virtual environment if you do not already have one, then install the project dependencies:

```bash
python3 -m venv .venv-multi
./.venv-multi/bin/python -m pip install --upgrade pip
./.venv-multi/bin/python -m pip install -r requirements.txt
```

Configure local credentials in the repository-root `.env`. If it does not exist, copy the root template:

```bash
if [ ! -f .env ]; then
  cp .env.example .env
fi
```

Set `DATABASE_URL` to the development Neon pooled connection and `MILVUS_URI` and `MILVUS_TOKEN` to the development Milvus endpoint. Keep `MILVUS_COLLECTION=agentic_customer_support_dev_policies_v1` and `EMBEDDING_MODEL=sentence-transformers/all-MiniLM-L6-v2` consistent with the indexed collection. Start the local Laya playground on port `8770`; keep `LAYA_BASE_URL=http://127.0.0.1:8770` and `LAYA_ENDPOINT_PATH=/api/predict` in `.env`. For `laya-serve`, use `LAYA_ENDPOINT_PATH=/v1/systemone`. Set `LAYA_API_KEY` only if that service requires it. If Laya is unavailable, classification falls back to the TF-IDF model and the response explicitly marks that fallback for human review. Do not use production credentials or commit `.env` files. For data preparation, classifier training, and policy indexing steps, follow [Day 2 preparation](#day-2-preparation), [Day 3 baselines](#day-3-baselines), and [the SQL + Milvus setup guide](docs/sql_milvus_integration.md).

Start the FastAPI development server bound to localhost:

```bash
APP_ENV=local EMBEDDING_MODEL=sentence-transformers/all-MiniLM-L6-v2 \
  ./.venv-multi/bin/python -m uvicorn backend.app.main:app \
  --host 127.0.0.1 --port 8000
```

In another terminal, start the Streamlit control room, also bound to localhost:

```bash
./.venv-multi/bin/python -m streamlit run frontend/app.py \
  --server.address 127.0.0.1 --server.port 8501
```

For the protected LangGraph workflow, apply the workflow storage setup described in [the Day 5 guide](docs/day5_langgraph_workflow.md), then start a worker in another terminal:

```bash
APP_ENV=local ./.venv-multi/bin/python -m backend.app.worker
```

Open [http://127.0.0.1:8501](http://127.0.0.1:8501). The UI includes the protected investigation workflow and live graph timeline, a fixture data explorer, single and labeled-set RAG evaluation, proposal review, and an agent/data-flow overview. See [the Streamlit UI guide](docs/streamlit_ui.md) for details. Keep both services on loopback: the legacy ticket, order, policy, and RAG evaluation routes are local-development endpoints.

In another terminal, confirm the process is up and open the interactive API docs:

```bash
curl -sS http://127.0.0.1:8000/health
```

Open [Swagger UI](http://127.0.0.1:8000/docs). To try a fixture ticket investigation, use:

```bash
curl -sS -X POST http://127.0.0.1:8000/tickets/investigate \
  -H 'Content-Type: application/json' \
  -d '{"schema_version":"1.0","ticket_id":"T-003","top_k":3,"methods":["semantic","keyword"]}'
```

The investigation combines review-only ticket classification with read-only Neon order/customer-context evidence and versioned Milvus policy excerpts. Stop the server with `Ctrl+C`. The authenticated `POST /workflows` endpoint is the intake path for a new message; it persists workflow state, while `POST /tickets/classify` only returns a classification preview. To run the automated suite:

```bash
./.venv-multi/bin/python -m unittest discover -s tests -p 'test*.py' -v
```

To run the local stdio MCP server instead, use a separate terminal from the repository root:

```bash
APP_ENV=local EMBEDDING_MODEL=sentence-transformers/all-MiniLM-L6-v2 \
  ./.venv-multi/bin/python -m backend.app.mcp_server.server
```

The legacy Day 4 API and MCP tools are local development-only and have no authentication or order-ownership authorization. Keep them on `127.0.0.1`. The Day 5 `/workflows`, `/proposals`, and `/approvals` routes require bearer authentication and per-resource scope; see [the LangGraph workflow guide](docs/day5_langgraph_workflow.md). Workflow starts are persisted to a PostgreSQL queue and executed by `backend.app.worker`. The graph still reads only fictional development fixtures and synthetic draft policies, so it is not a production deployment.

## Day 2 preparation

From the repository root, run:

```bash
./.venv-multi/bin/python scripts/generate_support_context_fixtures.py
./.venv-multi/bin/python scripts/prepare_data.py
./.venv-multi/bin/python scripts/train_classifier.py
```

The generator adds 180 synthetic loyalty tickets and creates synthetic loyalty account/ledger rows and PII-minimized communication summaries under `data/synthetic/`; `data/raw/` remains unchanged. It is repeatable and refuses to overwrite a conflicting ticket ID. The preparation step writes cleaned samples, an intent evaluation set grouped by linked customer and normalized message template, and a manifest under `data/processed/`, plus the ticket/order mapping under `data/synthetic/`. The training command refreshes the local TF-IDF fallback model. None of these commands connects to Neon or Milvus.

To evaluate the live Laya model on that held-out fixture set, start the local Laya service and run:

```bash
APP_ENV=local ./.venv-multi/bin/python scripts/evaluate_laya_classifier.py
```

The report records Laya accuracy, macro F1, abstentions, high-confidence errors, strict Laya/TF-IDF consensus coverage, and per-case predictions. The scores describe synthetic fixtures only; do not enable automatic routing from this small evaluation.

### Add customer-context tables to a development Neon branch

The API lookup stays read-only. Apply the additive migration and load fixtures only against a development Neon branch. First set `CUSTOMER_CONTEXT_WRITE_DATABASE_URL` to that branch's write-enabled direct connection in the local environment. Then:

```bash
psql "$CUSTOMER_CONTEXT_WRITE_DATABASE_URL" -v ON_ERROR_STOP=1 \
  -f backend/app/db/migrations/002_customer_support_context.sql
APP_ENV=local ALLOW_DEVELOPMENT_CONTEXT_SEED=true \
  ./.venv-multi/bin/python scripts/load_customer_context_to_neon.py
```

The migration creates three tables without dropping existing data. The seed script uses upserts and refuses to run unless both the local environment and explicit opt-in are set. Grant the runtime database role `SELECT` on these three tables if it differs from the migration role. Do not use production credentials. The new endpoint is `GET /orders/{order_id}/customer-context`; the matching read-only MCP tool is `get_customer_support_context`.

To refresh the local policy chunks after adding the synthetic loyalty draft, run `./.venv-multi/bin/python scripts/chunk_versioned_policies.py`. Indexing is a separate write to the development Milvus collection; follow the Day 3 steps below when you intend to refresh that external index.

After preparation, run the fixture and Day 2 quality checks:

```bash
./.venv-multi/bin/python -m unittest discover -s tests -p 'test*.py' -v
```

These checks cover the local fictional fixture and prepared artifacts. They do not test a live Neon or Milvus connection.

## Day 3 baselines

Install `requirements.txt` in the development environment. From the repository root:

```bash
./.venv-multi/bin/python -m pip install -r requirements.txt
```

The runtime intent classifier uses Laya's typed-choice endpoint; the held-out set is small and scores are not calibrated, so predictions remain review-only. TF-IDF plus logistic regression remains the explicit fallback and offline baseline. The policy pipeline chunks only versioned synthetic development documents under `knowledge_base/`, uses the locally cached `all-MiniLM-L6-v2` model, and targets the separate `agentic_customer_support_dev_policies_v1` Milvus collection. The existing unversioned collection is left untouched.

```bash
./.venv-multi/bin/python scripts/train_classifier.py
./.venv-multi/bin/python scripts/chunk_versioned_policies.py
EMBEDDING_MODEL=sentence-transformers/all-MiniLM-L6-v2 ./.venv-multi/bin/python scripts/index_dev_policies.py
EMBEDDING_MODEL=sentence-transformers/all-MiniLM-L6-v2 ./.venv-multi/bin/python scripts/evaluate_day3_rag.py
```

Search both baselines for a question with:

```bash
EMBEDDING_MODEL=sentence-transformers/all-MiniLM-L6-v2 ./.venv-multi/bin/python scripts/retrieve_policy.py "What should support do if a delivered scan conflicts with a non-receipt report?" --mode both
```

For a local HTTP evaluation endpoint and step-by-step Swagger/curl instructions, see [RAG Evaluation API](docs/rag_evaluation_api.md).

To combine a read-only order lookup from Neon with separate policy evidence from Milvus, see [SQL + Milvus investigation](docs/sql_milvus_integration.md). This combined route is local-development-only and uses fictional order fixtures and synthetic draft policies.

Day 4 adds schema-validated ticket/order/policy endpoints and local stdio MCP tools over the same read-only service layer. See [Day 4 API and MCP guide](docs/day4_api_and_mcp.md) for endpoints, request examples, and local host setup. These routes have no authentication or order-ownership authorization and must remain bound to localhost.

Milvus credentials belong in the ignored local environment file. The indexer refuses collection names without `_dev` and indexes only draft, synthetic, development-only documents. It does not index the captured retailer PDFs or claim those drafts are approved policy.

## Folder layout

The repository root is the canonical project root. Keep project code and artifacts directly in the documented structure; do not add another wrapper folder around them:

```text
.
├── backend/app/       # FastAPI, tools, agents, domain, data access, security
├── archive/           # archived or unintegrated legacy material
├── data/              # raw/, processed/, synthetic/
├── docs/              # requirements, contracts, reports, run guides
├── frontend/          # Streamlit control room
├── knowledge_base/    # versioned policy and FAQ sources
├── models/            # local classifier artifacts
├── notebooks/         # exploratory data analysis
├── output/            # generated or captured artifacts
├── scripts/           # preparation, training, indexing, evaluation
├── tests/             # unit, API, integration, and security tests
├── requirements.txt
├── .env.example
└── README.md
```

Do not put generated policy indexes, model artifacts, secrets, or operational exports beside application source files.
