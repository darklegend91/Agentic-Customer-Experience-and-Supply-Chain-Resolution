# Streamlit control room

The UI lives at `frontend/app.py` and calls the project's FastAPI contracts. It does not connect directly to Neon, Milvus, or Laya.

## Start it locally

Install the root requirements if needed, set the local values in the ignored repository-root `.env`, and start Laya plus FastAPI using the steps in [the Day 5 workflow guide](day5_langgraph_workflow.md). Then, from the repository root, run:

```bash
./.venv-multi/bin/python -m streamlit run frontend/app.py \
  --server.address 127.0.0.1 --server.port 8501
```

Open `http://127.0.0.1:8501`. Set the FastAPI URL and support/reviewer tokens in the sidebar if they are not already in `.env`. The support and reviewer tokens must identify different actors. The UI uses password inputs for the tokens and does not save them to project files.

## What the UI shows

- **Investigation workbench:** Submit a ticket ID, message, order ID, and retrieval settings. Watch persisted workflow events and the current LangGraph node, inspect Laya's intent/confidence/fallback/consensus flags, see the selected specialist, review order, delivery, loyalty, prior-contact, and Milvus evidence, inspect the typed evidence ledger and deterministic rule output, and submit a human approval decision when a proposal is pending.
- **Data explorer:** Use the local ticket classifier and investigation endpoints, read order/delivery/return facts through one combined SQL-backed request, optionally inspect loyalty/prior-contact context, combine an order lookup with policy search, and inspect retrieved policy passages.
- **RAG evaluation lab:** Evaluate one query with optional expected labels or run the checked-in labeled set, including a synthetic loyalty-policy case. Compare Hit@1, Hit@k, MRR, scope compliance, citation metadata, and returned excerpts for semantic and keyword search.
- **Agents & data flow:** View the processing stages, storage boundaries, agent responsibilities, and read-only MCP tool surface.

The workflow API returns `202` after storing the workflow and job payload in PostgreSQL. A separate `backend.app.worker` process claims the job and runs the graph; the UI polls `GET /workflows/{id}`, `/events`, and `/trace`. The trace API applies the same workflow, ticket, and order authorization checks and only returns the structured working outputs needed by the UI; it does not return the raw customer message.

## Local development boundary

Keep Streamlit and FastAPI bound to loopback. The legacy ticket/order/policy and RAG evaluation endpoints use fictional fixture data and do not all require authentication; the UI only calls those explorer endpoints when the API hostname is `localhost`, `127.0.0.1`, or `::1`. Workflow endpoints still require their bearer credentials and scoped authorization.

Workflow start jobs are durable and can be reclaimed after a worker lease expires. Approval resume still executes in the API request and does not have automatic retry after a process failure. Production still needs approved identity/resource scopes, operational data and policy sources, and operational controls before exposing this UI.

Approval is **simulation only**. No endpoint or UI control executes refunds, replacements, payments, order changes, or customer messages. The current Milvus content consists of synthetic draft policies and must not decide customer eligibility.
