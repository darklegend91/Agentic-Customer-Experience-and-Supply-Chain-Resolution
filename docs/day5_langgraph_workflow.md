# Day 5 LangGraph workflow

Status: implemented as a local development workflow; production data access remains disabled by the existing read-only fixture boundary.

## Workflow

The graph in `backend/app/agents/graph.py` executes:

```text
validate and mask input
  -> Laya triage (TF-IDF fallback is review-only)
  -> deterministic allowlisted supervisor route
  -> one specialist: policy FAQ | order/delivery | returns/refunds | product issue | loyalty/rewards
  -> consolidate SQL and policy evidence
  -> deterministic policy/evidence gates
  -> grounded answer OR safe clarification/escalation OR proposal interrupt
  -> persist final workflow status
```

Laya proposes an intent and a local TF-IDF classifier provides a second opinion. The model cannot name a tool, write SQL, or select an arbitrary graph node. Automatic routing is off by default; fallback, disagreement, abstention, and low confidence require review. The current workflow routes review cases to a human before specialist tools run. Specialist nodes call only bounded, read-only Neon and Milvus tools. The loyalty specialist uses synthetic ledger and communication records in local development only.

Evidence consolidation builds a typed ledger with source-record facts, retrieved policy passages and their lifecycle/scope applicability, customer reports, classifier assumptions, missing information, and detected conflicts. For workflow answers, every claim and citation list must exactly match deterministic claims generated from cited read-only sources, and the answer must match their canonical rendering. This blocks unsupported additions structurally; it does not prove general semantic entailment, so free-form paraphrasing remains disabled.

Return eligibility and late-refund rules validate required order/item/return evidence, then escalate unless an approved applicable policy and a supported machine-readable rule are available. Reward balance, expiry, and redemption-status questions may return complete ledger facts. Requests to change points, extend expiry, or determine redemption eligibility escalate. The current policies are drafts, so they cannot produce eligibility decisions.

The current Milvus collection contains synthetic draft policies only, including a synthetic rewards FAQ. Policy-dependent eligibility and remedy requests therefore escalate. Future decisions require approved lifecycle status, production scope, exact marketplace, intent and locale metadata, valid provenance, matching effective dates, and a supported machine-readable rule. The graph's interrupt path is only a simulation, not an external action.

## State and approval boundary

The graph checkpoints a masked ticket message, classification, scoped references, evidence, evidence hash, resolution result, and proposal. Email addresses, phone numbers, and payment-card-like numbers are redacted before checkpointing. SQL order reads continue through the existing read-only `DATABASE_URL`. Checkpoints, workflow status, events, proposals, and decisions use a separate write-enabled `WORKFLOW_DATABASE_URL`.

Approval pauses with LangGraph `interrupt()` and a durable `thread_id`. The approval API authenticates a reviewer, requires a distinct reviewer from the workflow creator, checks the expected proposal version, and re-reads evidence before accepting an approval. A changed or unavailable evidence snapshot invalidates the proposal. Rejection does not require a successful evidence refresh. An accepted approval resumes the graph and records **approved simulation only**. No order, return, refund, replacement, payment, or customer-contact action exists in the graph.

Approval requests require an `Idempotency-Key`. Replays with the same key and same decision return the recorded result; reusing the key for a different request conflicts. Events are append-only; proposal/workflow status is updated as the graph advances.

## Configure local development

Install requirements and configure a write-enabled development Postgres URL distinct from the read-only order URL:

```bash
./.venv-multi/bin/python -m pip install -r requirements.txt
```

Set these values in the ignored repository-root `.env`:

```dotenv
APP_ENV=local
DATABASE_URL=<existing read-only Neon fixture URL>
WORKFLOW_DATABASE_URL=<write-enabled development Postgres URL>
WORKFLOW_API_TOKEN=<random support token>
WORKFLOW_REVIEWER_TOKEN=<different random reviewer token>
WORKFLOW_API_ACTOR_ID=local-support-agent
WORKFLOW_REVIEWER_ID=local-reviewer
LANGGRAPH_STRICT_MSGPACK=true
```

Generate random local tokens in a terminal with:

```bash
python3 -c 'import secrets; print(secrets.token_urlsafe(32))'
```

Generate two different values. Never use production order credentials for workflow storage. Apply the workflow tables and LangGraph checkpoint tables once:

```bash
./.venv-multi/bin/python scripts/setup_workflow_storage.py
```

This command requires `WORKFLOW_DATABASE_URL`, applies `backend/app/db/migrations/001_workflow_storage.sql` and `003_workflow_job_queue.sql`, then runs LangGraph's Postgres checkpointer setup. It does not alter the order fixture schema.

Start Laya and the FastAPI service in separate terminals. Keep FastAPI bound to loopback:

```bash
APP_ENV=local EMBEDDING_MODEL=sentence-transformers/all-MiniLM-L6-v2 \
  ./.venv-multi/bin/python -m uvicorn backend.app.main:app \
  --host 127.0.0.1 --port 8000
```

Start the workflow worker in a separate terminal:

```bash
APP_ENV=local ./.venv-multi/bin/python -m backend.app.worker
```

## Endpoints

`POST /workflows` starts an investigation. The support token is for workflow creation; local development tokens are scoped to the fictional fixture only.

```bash
curl -sS -X POST http://127.0.0.1:8000/workflows \
  -H 'Authorization: Bearer <WORKFLOW_API_TOKEN>' \
  -H 'Content-Type: application/json' \
  -d '{
    "schema_version": "1.0",
    "message": "Where is my order ORD-ID-44319aea3c?",
    "top_k": 3,
    "methods": ["semantic", "keyword"]
  }'
```

The API returns `202 Accepted` with a `workflow_id` after atomically persisting the workflow and its job payload. A separate worker claims jobs from PostgreSQL using leases, renews its lease during execution, and reclaims work after a worker restart. LangGraph checkpoints let a retry continue from saved graph state. Inspect status with `GET /workflows/{workflow_id}`, stage/audit events with `GET /workflows/{workflow_id}/events`, the current graph node and structured working evidence with `GET /workflows/{workflow_id}/trace`, and a proposal with `GET /proposals/{proposal_id}`. The trace endpoint uses the same caller/resource checks as the workflow status endpoint and never returns the raw customer message.

When a consequential proposal is pending, approve or reject the exact version:

```bash
curl -sS -X POST http://127.0.0.1:8000/approvals/proposals/<proposal-id>/decision \
  -H 'Authorization: Bearer <WORKFLOW_REVIEWER_TOKEN>' \
  -H 'Idempotency-Key: <unique-request-id>' \
  -H 'Content-Type: application/json' \
  -d '{
    "schema_version": "1.0",
    "decision": "approve",
    "expected_proposal_version": 1,
    "comment": "Reviewed for simulation"
  }'
```

`approve` records approval for a simulation and never executes a customer action. The proposal and approval response include `action_execution_status: "not_available"`; the service rejects non-simulation proposal kinds. Audit events contain workflow stage and outcome metadata, not ticket message text or raw database rows.

The Streamlit control room displays the workflow timeline, classification, specialist evidence, policy excerpts, deterministic rules, draft validation, and approval gate. Start it with `./.venv-multi/bin/python -m streamlit run frontend/app.py --server.address 127.0.0.1 --server.port 8501`; see [the UI guide](streamlit_ui.md). Workflow starts are processed by `backend.app.worker`, not a FastAPI background task. The PostgreSQL queue reclaims expired worker leases. Approval decisions still resume the graph synchronously in the API process; automatic retry of a failed approval resume is not implemented yet.

## OIDC for a deployment

When `OIDC_ISSUER` or `OIDC_AUDIENCE` is set, the API requires a signed RS256/ES256 bearer token and validates signature, issuer, audience, expiry, and subject using the configured `OIDC_JWKS_URL`. The token must carry the configured support/reviewer role claim. Resource claims `order_ids`/`allowed_order_ids` and `ticket_ids`/`allowed_ticket_ids` scope each caller. The local static tokens are disabled outside local environments.

The rest of this project still uses local-only synthetic records and a development-only Milvus collection, so OIDC support does not make the overall service a production deployment. Production rollout requires an approved data source, policy corpus, tenant-aware resource authorization, retention/operations controls, and review of the LLM provider if enabled.

## Optional response model

By default, the graph drafts answers from fixed templates and validated read-only facts. To use an OpenAI-compatible draft endpoint, set `LLM_ENABLED=true`, `LLM_BASE_URL`, `LLM_MODEL`, and an optional `LLM_API_KEY` in the secret environment. Laya remains the classifier/router. The response model has no tools and receives only a compact evidence payload. Model failure, invalid JSON, unsupported citations, contact data, or a claim that an action was already executed sends the case to safe review. The structural validator verifies that citations exist; semantic entailment still needs a reviewed evaluation set before enabling model drafts for customer use.

## Tests

Run the mocked workflow tests without Neon, Milvus, Laya, or workflow database credentials:

```bash
./.venv-multi/bin/python -m unittest tests.agents.test_day5_workflow -v
```

The tests cover allowlisted specialist routing, a grounded order-status response, rejection of an out-of-scope order before classification, review-only classifier fallback, and interrupt/resume of an approved simulation. They do not verify remote database credentials, deployed OIDC claims, live Milvus policy scope, or semantic answer grounding.
