# Sanitization Implementation Plan

> **For agentic workers:** Execute inline using test-driven development, then request one independent security review.

**Goal:** Add a deterministic sanitization agent and repeatable dependency checks.

**Architecture:** A standard-library scanner supports input, evidence and output
boundaries. The LangGraph sanitization node runs before assessment; stored tickets
and shared tools apply the same checks independently.

**Tech Stack:** Python, unittest/pytest, LangGraph, pip-audit, GitHub Actions.

**Spec:** ../specs/2026-11-18-sanitization-design.md

## Constraints and rulings

- No new runtime dependency, live action executor, deployment or commit.
- Work in the existing checkout because required behavior is already modified
  there; preserve all preexisting changes.
- Baseline: 90 unittest cases, 9 failures (including 3 subtests), 6 errors.
  Keep the baseline log at `/tmp/agent-security-baseline.log` for comparison.

## Tasks

- [x] Write failing security tests for direct/encoded/Unicode override, role
  spoofing, dependency/command payloads, secrets, legitimate support text,
  independent queries, oversized input, stored tickets and poisoned evidence.
- [x] Implement `guardrails/content_safety.py` and `agents/sanitization.py`.
  Integrate with graph, input preparation, shared classification/retrieval,
  investigation, response generation and output validation. Test before each fix.
- [x] Audit installed dependencies without mutating the app environment. Add a
  validated dependency-source check, pinned/hash-verified install guidance and CI
  vulnerability scanning. Record any unresolvable advisories explicitly.
- [x] Run focused security and regression tests, run the full suite, request an
  independent security review, address substantive findings, and record results
  in `docs/security_verification.md`.

## Review focus

Caller-controlled query distinct from message; stored-ticket replacement;
indirect injection in policy/communication/order text; encoded payload bounds;
legacy paths and generated response leakage. Each is covered by security tests.
