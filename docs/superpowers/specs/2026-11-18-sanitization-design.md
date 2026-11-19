# Sanitization agent and dependency safeguards

The requested change adds a deterministic sanitization agent to the existing
LangGraph application and strengthens the boundaries around model input/output.
It uses Python's standard library and does not install packages at runtime.

## Approach

A separate LLM-based guard would add cost, another untrusted decision, and more
dependencies. A prompt-only instruction would leave the current ingress gaps.
Use deterministic screening alongside the existing model safety check, scoped
read-only tools, allowlisted routing, and separate approval authorization.
This is an implementation choice within the requested security work.

## Boundaries

- Screen caller messages and independent retrieval queries before classification
  or retrieval; repeat screening after loading a stored ticket. Normalize Unicode
  and inspect bounded decoded variants without executing payloads. Reject invalid
  and excessive input rather than silently truncating it.
- Register an explicit `sanitize_input` graph stage. Block suspicious input and
  retain only reason codes in its audit event. Keep old checkpoint nodes usable.
- Screen all specialist evidence before rules or response drafting, including
  policy excerpts and prior communication summaries. Fail closed on unsafe,
  excessively large, or malformed content; do not salvage an instruction by
  deleting a few words.
- Mask contact details and credential-like values before checkpoint/model use.
  Screen generated answers for instructions, active markup, exfiltration links,
  and secrets. Preserve deterministic claims and existing approval checks.
- Audit installed distributions for known advisories and inspect dependency
  sources. Add a repeatable manifest check and CI audit; do not claim that an
  advisory scanner proves a package is free of malware.

## Validation and limits

Use adversarial and ordinary support fixtures to test both rejection and useful
operation, including compact order requests, legacy/MCP paths and stored tickets.
Run the existing suite and report baseline failures by name. No filter guarantees
all prompt attacks are detected; model/tool isolation remains the security
boundary. Dependency advisories, provenance and deployment image contents require
continued review. Preserve existing uncommitted work; do not deploy or commit.
