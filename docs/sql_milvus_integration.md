# Read-only SQL + Milvus investigation

## What is connected

`POST /support/investigate` orchestrates two independent evidence lookups in the API:

1. Neon Postgres is queried for one order ID using parameterized, read-only SQL. The response contains allowlisted order, item, delivery-event, and return/refund fields.
2. Milvus retrieves policy passages using semantic search. The keyword baseline ranks the same development-only chunks locally with TF-IDF; it does not query Milvus.
3. The API returns the two evidence sets side by side, with SQL evidence references and Milvus document IDs, versions, sections, and excerpts.

Order records stay in SQL. They are not copied to Milvus or embedded. The route does not perform updates, refunds, or any other operational action. It omits customer identifiers and contact information.

## Local setup and run

Use the local fictional fixture only. Put the Neon pooled `DATABASE_URL`, `MILVUS_URI`, and `MILVUS_TOKEN` in the ignored repository-root `.env` file. Do not paste credentials into source code, tickets, or chat. The collection defaults to `agentic_customer_support_dev_policies_v1`.

The lookup is disabled unless `APP_ENV` is explicitly set to `local`, `dev`, or `development`. From the workspace root, start the local server with:

```bash
APP_ENV=local EMBEDDING_MODEL=sentence-transformers/all-MiniLM-L6-v2 ./.venv-multi/bin/python -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000
```

The embedding model must match the one used to build the Milvus index. Keep the server bound to `127.0.0.1`; this development API has no identity authentication or order-ownership checks. Open [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs), choose `POST /support/investigate`, and submit:

```json
{
  "order_id": "ORD-ID-adb5bc6dc0",
  "query": "Where is my order?",
  "top_k": 3,
  "methods": ["semantic", "keyword"]
}
```

That ID is the first synthetic order in `data/raw/orders.csv`. Use an order ID that exists in the connected development Neon database; otherwise the API returns `404`. The equivalent command-line request is:

```bash
curl -sS http://127.0.0.1:8000/support/investigate \
  -H 'Content-Type: application/json' \
  -d '{"order_id":"ORD-ID-adb5bc6dc0","query":"Where is my order?","top_k":3,"methods":["semantic","keyword"]}'
```

The response has an `order_evidence` object sourced from Neon and a `policy_evidence` object keyed by retrieval method. Each SQL row has an `evidence_refs` identifier. Each policy hit includes its document ID, policy version, section, source metadata, and excerpt. The `policy_scope_notice` is deliberate: the indexed policy documents are synthetic drafts in `synthetic-fixture` scope, so they are not approved policy for an order in `Amazon.in` or another real marketplace.

## Synthetic loyalty and prior-contact context

The ticket-investigation and LangGraph workflow paths can also read a bounded customer-context record linked through the order: the synthetic points snapshot, up to 50 ledger events, and up to 20 PII-minimized prior-contact summaries. No customer ID, email, or phone is returned. The read-only endpoint is `GET /orders/{order_id}/customer-context`; the MCP equivalent is `get_customer_support_context`.

The source CSVs live under `data/synthetic/`, not `data/raw/`. Apply `backend/app/db/migrations/002_customer_support_context.sql` and load those fixtures only to a development Neon branch, using the explicit write URL and opt-in documented in the [README](../README.md#add-customer-context-tables-to-a-development-neon-branch). If the optional tables are missing, the customer-context lookup returns `insufficient_data` with the missing source called out; it does not invent an empty ledger. The core `GET /orders/{order_id}/investigation` endpoint remains independent and reads order, item, delivery, and return/refund evidence in one bounded SQL statement. This customer context is not indexed into Milvus.

Common outcomes:

- `200`: SQL order facts and requested retrieval results were returned.
- `404`: the order ID is not in the development fixture.
- `422`: the request body is invalid.
- `503`: Neon, Milvus, or the configured embedding model is unavailable, or the development lookup is disabled by `APP_ENV`.

## Production requirements

This endpoint is for local development only. Before exposing an equivalent production workflow, put it behind authenticated identity and authorization, check the caller's access to the requested order, use a least-privilege read-only database role, and record an audit event. Keep SQL and policy evidence separately sourced. Production retrieval must target an approved, versioned policy collection and filter for the order's marketplace and policy effective dates. The current synthetic draft collection must not drive customer decisions. Keep credentials in the deployment secret manager and use a private network path to both services.
