# Private demo deployment

This runbook deploys the synthetic-data MVP to one Linux VM with Docker Compose. It is a **private demonstration deployment**, not production customer support. The VM runs FastAPI, a durable workflow worker, Streamlit, and Caddy. Neon and Zilliz/Milvus remain managed external services. Laya must be reachable through a private network address.

## Scope and compute

Project 5 requires Python 3.11+, Docker/Compose, FastAPI, Streamlit, LangGraph, PostgreSQL, and Milvus. Its scope uses public or synthetic records and excludes production-scale multi-tenant deployment, real customer data, and live actions. The brief specifies no cloud provider or numeric CPU/RAM/GPU budget.

Use a general-purpose CPU VM for a first demo. A conservative starting estimate is **4 vCPUs and 12 GiB RAM** for the API, worker, UI, proxy, and cached MiniLM model, with Laya on a separate private service. The API and worker each load the embedding model in their own process. If Laya must share the VM, measure its model footprint and increase the VM size before deployment. A GPU is not required by this project’s embedding model; Laya’s compute needs depend on the model served by that separate component. Reduce this size only after checking peak memory and latency with the deployed services.

## Network layout

- Public ingress reaches Caddy on ports 80 and 443 only.
- Caddy proxies to Streamlit and requires HTTP Basic authentication. Restrict network access further with a VPN or identity-aware gateway if available.
- FastAPI, the workflow worker, and Laya have no public host ports. Containers reach FastAPI at `http://api:8000` and Laya at its private service address.
- Restrict SSH to an administrator source address or use the cloud provider's managed shell.
- Do not use real tickets, customer data, production order systems, or production credentials.

The app runs with `APP_ENV=local` for this synthetic demo so its protected workflow routes can use distinct local support/reviewer tokens. That mode also enables unauthenticated fixture endpoints. Network isolation and the access gateway are mandatory for this deployment. Do not use this mode for production.

## Before deploying

1. Create a Linux VM with a static IP, a DNS name, and the resource estimate above. Place it in the same or a nearby region as the development Neon and Zilliz services to limit network latency.
2. Configure the firewall for ports 80/443 and restricted administrative access only.
3. Create a development Neon branch with fictional data. Do not copy this project's fixtures into a production branch.
4. Configure a separate write-enabled Neon database/schema for workflow records and LangGraph checkpoints. Keep the order fixture connection read-only. Use a pooled connection for normal order reads and a direct connection for schema migrations.
5. Confirm that the development Milvus collection `agentic_customer_support_dev_policies_v1` exists and has the intended synthetic draft passages. Use a read-only runtime credential where supported; use a separate write credential for any indexing job.
6. Host Laya so it is reachable from the VM over a private address. The local value `http://127.0.0.1:8770` points to the container itself after containerization and will not reach Laya on another host.
7. Copy the repository to the VM from your reviewed source branch. Do not copy `.env`, local password files, `.venv`, raw datasets, or model caches into the build context.

## Configure secrets

Create runtime files on the VM from the checked-in examples. Keep the real values in the cloud secret manager or a root-owned file with restrictive permissions.

```bash
cp deploy/.env.api.example .env.api
cp deploy/.env.ui.example .env.ui
cp deploy/.env.deploy.example .env.deploy
chmod 600 .env.api .env.ui .env.deploy
```

Set real development-only values in `.env.api`:

- `DATABASE_URL`: pooled read-only development fixture connection.
- `WORKFLOW_DATABASE_URL`: a separate write-enabled development workflow/checkpoint connection.
- `MILVUS_URI` and `MILVUS_TOKEN`: the development collection endpoint and runtime credential.
- `LAYA_BASE_URL`: the private Laya address reachable from the API container.
- `WORKFLOW_API_TOKEN` and `WORKFLOW_REVIEWER_TOKEN`: distinct random values.
- `APP_ENV=local` and `LLM_ENABLED=false` for this synthetic demo.

Set `WORKFLOW_API_TOKEN` and `WORKFLOW_REVIEWER_TOKEN` to the same two values in `.env.ui`. Set `APP_DOMAIN` in `.env.deploy` to the DNS name that points at the VM. Generate a Caddy bcrypt hash for a long random demo password and set it as `ACCESS_HASH`; choose a non-default `ACCESS_USER`. Never commit any of these runtime files. The UI's API address is fixed to the internal Compose name `http://api:8000`, which prevents the UI from making server-side requests to an arbitrary address.

## Build and start

The Docker image installs the Python dependencies, creates the synthetic TF-IDF and policy-chunk artifacts, and caches `sentence-transformers/all-MiniLM-L6-v2` at build time. Runtime model loading is local-only. Build from the repository root:

```bash
docker compose --env-file .env.deploy build
```

Apply the workflow schema and LangGraph checkpoint schema once, before starting the API and worker:

```bash
docker compose --env-file .env.deploy run --rm --no-deps --entrypoint python api \
  scripts/setup_workflow_storage.py
```

Then start the services:

```bash
docker compose --env-file .env.deploy up -d
docker compose --env-file .env.deploy ps
```

Caddy obtains and renews HTTPS certificates for `APP_DOMAIN`. The Compose configuration publishes only Caddy's web ports; it does not publish ports 8000, 8501, or 8770 on the VM.

## Verify and operate

Open `https://APP_DOMAIN` from an allowed network and submit a synthetic ticket through the UI. The UI should show API health, the workflow stages, evidence, and—when the fixture produces one—the simulation-only approval flow. The API health endpoint is private; check it from inside the container network:

```bash
docker compose --env-file .env.deploy exec api \
  python -c 'import urllib.request; print(urllib.request.urlopen("http://127.0.0.1:8000/health", timeout=3).read().decode())'
```

Inspect service logs without printing environment values:

```bash
docker compose --env-file .env.deploy logs --tail=100 api worker ui proxy
```

Update by pulling a reviewed code revision, rebuilding, and recreating containers:

```bash
docker compose --env-file .env.deploy build
docker compose --env-file .env.deploy up -d
```

`docker compose down` preserves the Caddy certificate volumes. Do not pass `--volumes` unless you intend to delete them.

## Workflow recovery behavior

Workflow intake and the persisted job are written in one PostgreSQL transaction. The worker claims jobs with a lease, renews the lease while processing, and can reclaim jobs after a worker crash. Retries are bounded; exhausted jobs become `failed_safe`. LangGraph checkpoints let a retry continue from persisted graph state. Run at least one worker container; you may scale workers after measuring database, Milvus, and Laya capacity.

Approval decisions currently resume the graph synchronously in the API request. They are protected by idempotency and stale-evidence checks, but automatic retry of a failed approval-resume request is not yet handled by this queue. This remains a reliability item before production.

## Production release is not enabled

This runbook intentionally does not provide a production configuration. Before production use, the project still needs an approved OIDC provider and role mapping for the UI and every API route, trusted per-customer record authorization, a production data connector and read-only source role, approved and effective policy documents, retention/incident/operations targets, reviewed migration and rollback procedures, security regression evidence, and a durable approval-resumption job. The current records and policy index are fictional drafts. The project has no live refund executor, by design.
