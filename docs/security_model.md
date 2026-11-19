# Security and Access Boundaries

## Security objective

Allow an authenticated support user to investigate only records they are authorized to handle, using approved evidence, while preventing tickets, retrieved text, or model output from bypassing policy or triggering consequential actions.

## Principals and roles

| Principal | Access |
| --- | --- |
| Support agent | Scoped ticket, order, delivery, return, and policy reads; create a proposal |
| Supervisor | Agent permissions plus approve/reject a proposal within assigned scope |
| Policy manager | Manage policy drafts and publication lifecycle; no customer record access by default |
| Runtime service | Read-only operational tools; write only workflow, proposal, and safe audit records |
| Migration identity | Schema changes through reviewed migrations; never used by request-serving code |
| Ingestion identity | Publish approved policy metadata and index artifacts; no order/customer access |

Production authentication uses an organization-approved OIDC/JWT issuer. Validate issuer, audience, expiry, signature, and required role claims. The identity provider is not selected yet. Authorization must be enforced in the API and again inside each data tool.

## Data and tool boundaries

- Resolve customer/order access from trusted identity and server-side mappings. An order ID supplied in a ticket is only a lookup hint.
- Return only allowlisted fields. Do not expose full customer tables, unrelated orders, payment credentials, or arbitrary database rows.
- Use a database role with read-only access to operational views and separate write permissions for workflow state. Do not run the app as database owner.
- Use a separate migration identity and direct connection for schema migrations. Runtime uses the pooled application connection.
- Give the classifier, embedding model, and language model no database credentials and no arbitrary tool invocation.
- Read tools never mutate an order, return, refund, loyalty balance, address, or payment record.
- Customer-context rows are returned only through a bounded order-scoped join; direct customer IDs and contact fields are not included in the response. Prior-contact summaries and ledger descriptions remain untrusted data.
- Keep approval review separate from action execution. No live action executor is part of the MVP.

## Untrusted content

The `sanitize_input` LangGraph agent runs before request assessment. The shared
guard also runs before job persistence, classification and policy retrieval,
after stored-ticket lookup, on specialist evidence, and before response drafting.
Older checkpoints are rescreened before rules, proposal persistence and approval.
The sanitizer uses deterministic Python and adds no runtime dependencies or tools.

It screens direct instruction overrides, role delimiters, common command/package
installation and SQL payloads, active markup, Markdown reference links, Unicode
formatting tricks and bounded HTML/URL/base64/hex/escaped representations. Inputs
are limited to 5,000 message and 3,000 query characters; oversized stored tickets
are rejected. Decoding stops with rejection at its work limit. Nested evidence
has depth, size and type limits. Rejected evidence is cleared before checkpointing
the stage result. Audit events contain a version, verdict and reason codes only.

Contact identifiers, quoted credential values, Basic/Bearer credentials, private
keys and database connection strings are masked before initial job/checkpoint
storage. Encoded credential-like content is rejected. Generated responses are
checked again for secrets, instructions and unverified links. The generic LLM
must return the exact canonical answer and claims; Groq can select only fixed
opening/closing phrases around the exact verified facts. Invalid output uses
the deterministic fallback or escalates through the existing validation gate.

These are bounded heuristics with false positives and false negatives. They do
not establish safety against every language, encoding, model jailbreak, poisoned
source or resource-exhaustion attack. Scoped tools, parameterized queries,
deterministic rules and separate human approval remain the security boundaries.

## Dependency supply chain

`requirements.lock` pins runtime dependencies and distribution SHA256 hashes;
`requirements-security.lock` isolates the pinned auditing tools. The runtime
constraints retain versions audited in the current development environment, with
Python 3.11-compatible alternatives where a package requires Python 3.12 or newer.
Use a **fresh virtual environment**: pip does not revalidate hashes of packages
already installed. Use `--isolated --require-hashes --only-binary=:all:` and the
explicit `https://pypi.org/simple` index as shown in the README.

Run `python scripts/check_dependency_sources.py` before dependency changes. It
rejects unreviewed direct package names, unbounded requirements, custom indexes,
trusted-host bypasses, editable/VCS/URL requirements, escaping/recursive includes,
and unpinned or unhashed lock entries. It validates the constraints too. New direct
dependencies require an explicit review of the package allowlist. Resolved names
must also appear in `.security/dependency_allowlist.json`, preventing lock-only
package additions from bypassing the direct manifest check. Regenerate with:

```bash
uv pip compile requirements.txt --constraint requirements.constraints.txt --universal --python-version 3.11 --generate-hashes --default-index https://pypi.org/simple --no-config --output-file requirements.lock
```

The security workflow runs on pushes, pull requests and a weekly schedule. It
audits runtime and tool locks separately for known advisories and runs offline
security regressions in a fresh hash-verified Mac/Python 3.14 environment.
Actions are pinned by commit and have read-only repository permission.
The audit script includes all platform/Python marker variants, splitting multiple
versions of the same package into separate audit invocations.

A clean advisory scan does not prove absence of malicious packages, unpublished
vulnerabilities, tampered model files or compromised maintainers. Hashes establish
the selected artifact's identity, not its trustworthiness. Existing CPU-only
Docker images have their own pinned base-image provenance; these changes do not
rebuild or scan those images. A separate CPU-specific lock and image scan are
needed before changing their dependency installation path. No runtime agent has
a package-install, shell-execution or arbitrary-SQL tool.

Treat customer messages, product descriptions, order notes, captured webpages, policy excerpts, and model output as untrusted data. Flag instruction-override attempts, but do not rely only on keyword matching. Retrieved content cannot modify system instructions, data access, tool permissions, or approval requirements.

Retrieved policy text is usable only after source verification and policy-manager approval. Filter by active version, lifecycle, production scope, marketplace, intent, jurisdiction, and effective date before it can support a decision. The workflow's claim validator compares each claim and its cited references to an allowlisted deterministic source claim and rejects extra or rephrased answer content. This is a conservative source check, not a general semantic entailment proof for arbitrary natural language.

## Privacy and observability

- Minimize fields at ingestion and tool boundaries.
- Redact direct identifiers from external model prompts unless the data owner approves a documented necessity.
- General logs contain request ID, workflow stage, status, timing, and error category, not raw ticket text.
- Restrict detailed evidence and audit views to authorized roles.
- Define data retention, deletion, support access, and incident-response procedures with the data owner before production.
- Keep env files, tokens, API keys, database URLs, model artifacts containing user text, and raw traces out of version control.

## Environment controls

- Development and CI use fictional/synthetic fixtures.
- Staging uses synthetic or separately approved anonymized data and separate credentials.
- Production is protected; no developer experiment or test fixture writes to it.
- Test schema changes on isolated Neon branches and apply reviewed migrations through a deployment identity.
- Do not create a staging branch containing production personal data until masking and access controls are approved.

## Required security cases before launch

1. Ticket asks the assistant to ignore policy or reveal private records.
2. Retrieved text contains instructions to bypass access controls.
3. Caller supplies another customer's order reference.
4. Caller requests unsupported refund or compensation action.
5. Required evidence is missing, stale, or contradictory.
6. Approval is attempted by an unauthorized role or with a forged proposal ID.
7. Retrieval, database, model, or tool times out or returns malformed data.
8. Logs and traces are checked for raw messages, secrets, and direct identifiers.

Expected behavior is deny, clarify, or escalate with a safe audit event. Production release remains blocked until the identity provider, role mapping, retention period, and source-system access are approved.
