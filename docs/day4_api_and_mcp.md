# Day 4 — Read-only Investigation API and MCP Tools

## Scope and safety

Day 4 adds schema-validated FastAPI routes and a local stdio MCP server. Both interfaces use the same Python tools and repositories. Neon is queried through short-lived read-only transactions with parameterized SQL and bounded result counts. Policy search is restricted to the existing synthetic, development-only draft corpus in Milvus (semantic) and the local keyword baseline. Ticket responses never include `expected_intent` or `expected_handling`.

These interfaces are for local development against fictional fixtures. They do not authenticate callers or authorize order ownership, so bind the API to `127.0.0.1` and do not publish the API or MCP server to a network. The draft policy corpus cannot be used to decide customer eligibility. Production needs approved policy sources, identity and authorization middleware, least-privilege database roles, audit controls, and operational review.

## Day 4 plan check

| Project 5 Day 4 requirement | Implementation status |
| --- | --- |
| Ticket classification and investigation endpoints | Implemented at `POST /tickets/classify` and `POST /tickets/investigate`; classification now calls the configured local Laya `POST /v1/systemone` endpoint first and falls back to the TF-IDF baseline only in human-review mode. The investigation route accepts the Project 5 `ticket_id`, `message`, and `order_id` shape and rejects a message that conflicts with the stored ticket. |
| Read-only order, delivery, customer-context, and policy tools | Implemented for order summary/investigation, delivery events, recorded return/refund state, synthetic loyalty and prior-contact lookup, and versioned policy search. No mutation tool is registered. |
| Pydantic validation of tool inputs and outputs | Implemented with bounded requests, forbidden unknown fields, typed SQL evidence models, and typed policy evidence models. |
| Errors, deadlines, request IDs, and safe logs | Implemented with a consistent error envelope, request ID header, safe route-template logs, bounded HTTP/Neon/Milvus timeouts, and no raw ticket/query logging. |
| Explicit missing-record and insufficient-evidence results | Implemented as `404` for missing HTTP resources and `status: insufficient_data` plus `missing_fields` when records exist but evidence is absent. MCP lookup tools return structured `not_found` results. |
| Production identity and record authorization | Not enabled. `Project_5.docx` leaves the identity provider unselected, and the fixture has no trusted caller-to-ticket/order mapping. Every non-local API request therefore fails closed with `503`; do not remove that guard until those controls are implemented and tested. |
| Durable workflow status and audit persistence | Not part of this Day 4 implementation. Ticket lookup explicitly returns `workflow_status: "not_persisted"`; durable workflow/audit storage remains a later sprint requirement. |

The Day 4 development deliverable is complete and tested against the configured development services. The service is not approved for production traffic while the identity, record-authorization, approved-policy, and durable-audit items remain open.

## FastAPI routes

Start the API from the repository root after installing `requirements.txt`:

```bash
APP_ENV=local EMBEDDING_MODEL=sentence-transformers/all-MiniLM-L6-v2 \
  ./.venv-multi/bin/python -m uvicorn backend.app.main:app \
  --host 127.0.0.1 --port 8000
```

Open [Swagger UI](http://127.0.0.1:8000/docs). Day 4 POST bodies use `schema_version: "1.0"`; the existing Day 3 RAG evaluation and `/support/investigate` routes keep their original request contracts. Unknown fields, invalid IDs, unsupported retrieval methods, and out-of-range limits are rejected with `422`.

| Method and path | Purpose |
| --- | --- |
| `GET /health` | Process health |
| `GET /tickets/{ticket_id}` | Read ticket message and linked order hint |
| `POST /tickets/classify` | Review-only Laya intent choice, with explicit TF-IDF fallback status |
| `POST /tickets/investigate` | Ticket triage plus optional order and policy evidence |
| `POST /investigations/tickets` | Alias for ticket investigation |
| `GET /orders/{order_id}/summary` | Order facts and bounded items |
| `GET /orders/{order_id}/investigation` | Order, items, delivery events, and return/refund records in one API request and one SQL statement |
| `GET /orders/{order_id}/delivery-events?limit=100` | Chronological delivery scans |
| `GET /orders/{order_id}/returns-refunds?limit=50` | Recorded return/refund state; no eligibility decision |
| `GET /orders/{order_id}/customer-context` | Bounded loyalty ledger and PII-minimized prior-contact summaries (local fixture only) |
| `POST /policies/search` | Semantic, keyword, or both retrieval methods, scoped by validated `locale` (default `en-IN`) |
| `POST /support/investigate` | Existing Day 3 combined SQL + policy route |
| `POST /rag/evaluate`, `POST /rag/evaluate/labeled-set` | Existing Day 3 retrieval evaluation |

### Ticket classification

```bash
curl -sS http://127.0.0.1:8000/tickets/classify \
  -H 'Content-Type: application/json' \
  -d '{"schema_version":"1.0","message":"My order arrived damaged. What should I do?"}'
```

The response includes `intent`, `confidence`, `classifier_version`, `classifier_provider`, `fallback_used`, `baseline_intent`, `models_agree`, `risk_flags`, and `needs_human_review`. `classifier_provider` is `laya`, `tfidf_fallback`, or `input_guardrail`. Set `LAYA_BASE_URL` (default `http://127.0.0.1:8770`), `LAYA_ENDPOINT_PATH` (default `/api/predict` for the Laya playground; use `/v1/systemone` for `laya-serve`), optional `LAYA_API_KEY`, `LAYA_TIMEOUT_SECONDS`, `LAYA_MIN_CONFIDENCE`, and optional `LAYA_MODEL` in the root `.env`. The adapter uses Laya's `answer_confidence`, or the selected label's probability when using a strict Jev response; it does not use Laya's `confidence` field because that field has a different entropy-based meaning. The score is not calibrated. The last measured Laya result was 45% accuracy and 0.418 macro-F1 on 40 synthetic cases. A Laya timeout, invalid response, or unavailable endpoint falls back to the TF-IDF model and forces human review. Strict two-model consensus routing is disabled by default; the classifier preview never authorizes a consequential action.

The TF-IDF fallback has been retrained on a customer/template-grouped synthetic split (46 held-out cases, 23 labels; 91.3% accuracy, 0.894 macro-F1). Those results are not a production estimate. Run `APP_ENV=local ./.venv-multi/bin/python scripts/evaluate_laya_classifier.py` to evaluate Laya and consensus candidates on the refreshed holdout.

Check the Laya playground with `curl -i http://127.0.0.1:8770/api/health`. The application calls `POST /api/predict`; if the selected Laya server requires a bearer key, set it only in the ignored root `.env` or process environment. The choice is limited to the documented business intent taxonomy plus `other_or_unsupported`.

### Ticket investigation

Provide a stored fixture `ticket_id`, an inline `message`, or both. If you provide both, the message must match the stored ticket exactly; the service uses the ticket's mapped order hint. An explicit `order_id` must also agree with the ticket mapping and any order ID extracted from the message. The following uses a stored ticket and lets the service use its mapped order hint:

```bash
curl -sS http://127.0.0.1:8000/tickets/investigate \
  -H 'Content-Type: application/json' \
  -d '{"schema_version":"1.0","ticket_id":"T-003","top_k":3,"methods":["semantic","keyword"]}'
```

For an inline question without a stored ticket:

```bash
curl -sS http://127.0.0.1:8000/tickets/investigate \
  -H 'Content-Type: application/json' \
  -d '{"schema_version":"1.0","message":"Where is my order?","order_id":"ORD-ID-05a6699863","top_k":3,"methods":["semantic","keyword"]}'
```

The result keeps classification, SQL order facts, delivery/return records, customer context, policy excerpts, and a typed evidence ledger in separate fields. A missing order is reported as `not_found`; a missing database or retrieval dependency returns `503`. It does not generate a customer reply or infer policy eligibility.

### Policy search locale

`POST /policies/search` accepts a validated `locale` such as `en-IN`. Both semantic and keyword retrieval filter on locale before returning passages. The workflow independently checks policy lifecycle, marketplace, intent, locale, jurisdiction, and effective dates; a retrieved draft is evidence for review, not an applicable production rule.

```bash
curl -sS http://127.0.0.1:8000/policies/search \
  -H 'Content-Type: application/json' \
  -d '{"schema_version":"1.0","query":"How are reward points recorded?","locale":"en-IN","top_k":3,"methods":["semantic","keyword"]}'
```

### Loyalty and prior-contact evidence

`GET /orders/{order_id}/customer-context` and the MCP tool `get_customer_support_context` return a linked development account, bounded ledger rows, and short prior-contact summaries. The same context is included in the protected workflow trace. The migration and explicit synthetic-data seed steps are documented in the root README. Current rewards records and policy text are synthetic; this endpoint must stay local until a real programme, customer authorization contract, retention rules, and policy owner are approved.

## MCP server

Install the project dependencies, then start the local MCP server over stdio:

```bash
APP_ENV=local EMBEDDING_MODEL=sentence-transformers/all-MiniLM-L6-v2 \
  ./.venv-multi/bin/python -m backend.app.mcp_server.server
```

The MCP tool names are `get_ticket_details`, `classify_ticket`, `get_order_summary`, `get_order_investigation`, `list_delivery_events`, `get_return_refund_status`, `get_customer_support_context`, `search_policy`, and `investigate_ticket`. Their input types set bounds and allowed retrieval methods, and their outputs are validated with Pydantic response models. They are annotated as read-only hints; the server-side code and SQL transaction enforce read-only behavior independently of the client.

For an MCP host that accepts a stdio server configuration, point `command` at the workspace `.venv-multi/bin/python`, pass `-m backend.app.mcp_server.server`, and set `PYTHONPATH` to the absolute repository root, `APP_ENV=local`, and `EMBEDDING_MODEL=sentence-transformers/all-MiniLM-L6-v2`. The embedding model must match the model used to build the development Milvus collection; this project’s indexed collection and evaluation report use all-MiniLM-L6-v2. The server loads the ignored root `.env` file for database and Milvus configuration, but process environment values take precedence. Do not put credentials in the host configuration or source control.

Generic stdio configuration shape (replace the two absolute paths):

```json
{
  "mcpServers": {
    "agentic-customer-support-dev": {
      "command": "/absolute/path/to/workspace/.venv-multi/bin/python",
      "args": ["-m", "backend.app.mcp_server.server"],
      "env": {
        "APP_ENV": "local",
        "PYTHONPATH": "/absolute/path/to/repository",
        "EMBEDDING_MODEL": "sentence-transformers/all-MiniLM-L6-v2"
      }
    }
  }
}
```

The embedding model must already be cached locally; runtime inference does not download model files.

## Error meanings

- `200`: the requested local fixture evidence was returned.
- `404`: ticket or order ID is not present in the local fixture.
- `422`: request schema or field bounds failed.
- `insufficient_data`: a known record exists, but the evidence needed for the requested lookup is absent; the response lists `missing_fields`.
- `503`: local-only guard denied access, or Neon/Milvus/model dependency is unavailable.

Each HTTP response has an `X-Request-ID`; the same ID appears in response bodies that carry investigation metadata and in safe structured server logs. Logs use route templates and do not include request bodies, query text, IDs, SQL parameters, or exception messages. HTTP requests have a configurable 30-second default deadline, capped at 120 seconds; Neon connections and statements and Milvus searches have tighter dependency-level timeouts.

## Production follow-up

Before making an equivalent service available to support staff, add authenticated identity and server-side order/ticket authorization, verify the runtime Neon role is read-only, source policy passages from an approved lifecycle and marketplace scope, persist the ticket workflow status, add durable audit events with PII-safe fields, and run security and operational acceptance checks. The current service intentionally returns `workflow_status: "not_persisted"`; it has no caller-to-record authorization mapping or durable workflow/audit store. Keep every non-local environment disabled until those controls exist. MCP annotations do not provide these controls.
