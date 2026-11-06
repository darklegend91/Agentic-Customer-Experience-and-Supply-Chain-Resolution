# Production Oriented Architecture

## Purpose

This is the Day 1 target for a controlled support assistant. It is a production-oriented design; the current fixture, policy corpus, and code are not production-ready. The repository root is the canonical project root, following docs/Project_5.docx, Section 11.

## Decisions

| Area | Day 1 decision |
| --- | --- |
| API | FastAPI with Pydantic request and response contracts |
| Application data | Neon Postgres for ticket workflow, proposals, approval events, policy metadata, and audit references |
| Database code | SQLAlchemy 2.x models and Alembic migrations, versioned with the application |
| Order facts | Read-only, narrowly scoped source-system views or APIs; the model has no database credentials |
| Policy retrieval | Versioned policy files are authoritative; Milvus stores searchable chunks and metadata |
| Keyword baseline | Postgres full-text search or BM25 can supplement vector search; lifecycle and scope filters run first |
| Classification | Laya typed-choice classifier; explicit TF-IDF fallback remains review-only; ambiguous and security-sensitive cases route to review |
| Business decisions | Deterministic application rules validate eligibility and permitted actions |
| Human review | Consequential proposals enter a separate approval workflow; no refund or compensation executor is exposed |
| Identity | Verify an organization-approved OIDC/JWT issuer; provider selection remains an implementation gate |
| User interface | Streamlit is a demo surface; production access requires an authenticated internal support interface |
| Language model | Optional for evidence-grounded drafting; never responsible for authorization, policy decisions, or approvals |

## Request flow

~~~mermaid
flowchart LR
    A[Authenticated support user] --> B[FastAPI intake]
    B --> C[Validate request and authorize subject]
    C --> D[Classify intent and risk flags]
    D --> E[Read-only order, delivery, and customer-context tools]
    D --> F[Policy retrieval]
    E --> G[Evidence validation]
    F --> G
    G --> H[Deterministic policy checks]
    H --> I[Resolution proposal]
    I --> J{Consequential action?}
    J -->|No| K[Grounded response]
    J -->|Yes| L[Supervisor approval queue]
    B --> M[Neon Postgres workflow and audit records]
    L --> M
    F --> N[Milvus vector index]
    F --> O[Versioned policy source files]
~~~

## Trust and data boundaries

1. The API authenticates the caller and authorizes the requested customer/order relationship before invoking a tool.
2. Ticket text, external records, retrieved policy passages, and model output are data. None can grant permissions or change system instructions.
3. Read tools return typed, bounded results with source identifiers and an as-of timestamp. There is no arbitrary SQL, URL, or tool selection.
4. The policy index is filtered by marketplace, locale, approved lifecycle state, and effective date before results reach the workflow.
5. Deterministic rules decide which actions are allowed. A language model may draft from supplied evidence but cannot approve or execute actions.
6. The model service receives only the minimum redacted text needed for its task. It receives no database credentials or direct customer lookup capability.
7. Approval writes are isolated from read-only investigation tools. The MVP has no live refund, compensation, or loyalty-adjustment execution tool.

## Data placement

- Neon Postgres stores workflow state, proposals, approval events, policy metadata, evidence references, and audit metadata. The local fixture schema also has separate synthetic loyalty and prior-contact tables; production data needs its own approved source contract and authorization scope.
- Production order, delivery, rewards, and communication facts remain authoritative in their source systems. The application accesses them through read-only views or approved APIs; it does not silently become a second system of record. The current loyalty and prior-contact tables are synthetic development fixtures only.
- Versioned policy source files live under knowledge_base/. Milvus stores derived chunks and embeddings, never the only copy of a policy.
- Evaluation fixtures and generated artifacts stay outside production. Do not load the current fictional customer and order fixture into a production branch.
- Raw ticket content is stored only where the workflow requires it and under an approved retention policy. General logs and audit metadata do not contain raw messages.

## Environments and release path

Use isolated development, staging, and production environments. Development uses the fictional fixture. Staging uses synthetic data or a separately approved anonymized dataset. Production is protected and receives only reviewed migrations and approved policy releases.

For Neon, use a branch-first workflow: test schema changes on an isolated branch before promoting reviewed migration files. Use a pooled connection for application traffic and a direct, unpooled connection for schema migrations. Keep production credentials separate from development and CI credentials. The current codebase has no migration pipeline, identity provider, or production data connector; these remain implementation work.

Do not create, reset, or migrate a live branch as part of Day 1. A production release requires a reviewed migration, a rollback plan, an owner-approved data contract, and a staging run.

## Operational requirements

- Fail closed when authentication, authorization, policy retrieval, or evidence validation fails.
- Return explicit insufficient-evidence or escalation results instead of guessing.
- Bound request size, tool result size, retries, and timeouts.
- Include a request ID across API, tool, and approval events.
- Record the classifier and policy versions used for each proposal.
- Keep database roles separate for runtime, migrations, and policy ingestion.
- Manage credentials through the deployment secret manager. Local env files are for development only and are excluded from version control.
- Establish availability, latency, retention, backup, recovery, and incident-response targets with the service owner before production launch; this project has not set those targets.

## External references

- [Neon database branching workflows](https://neon.com/branching)
- [Neon production and staging branch guidance](https://neon.com/blog/practical-guide-to-database-branching)
- [Neon connection pooling and direct connections](https://github.com/neondatabase/website/blob/main/content/docs/get-started/connect-neon.md)
