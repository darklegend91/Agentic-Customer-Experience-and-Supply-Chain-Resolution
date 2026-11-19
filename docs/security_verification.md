# Security verification — 18 November 2026

## Observed results

- Focused offline security and agent regression suite: **46 passed**.
- Installed development environment: **233 distributions audited**, no known
  vulnerability advisories and no skipped distributions. `pip check` passed;
  no editable/VCS/direct-URL installations were recorded in installed metadata.
- Runtime and audit-tool locks: **159 distinct package/version pairs** across
  supported platform/Python variants, audited in two groups (153 + 6) to avoid
  pip-audit's duplicate-project-version restriction. No known advisories or skips.
- Hash-locked runtime installation dry run: all packages applicable to the current
  Mac/Python 3.14 environment were already satisfied at their tested versions.
  No application package was installed, upgraded or removed during this work.
- Dependency allowlist, constraints and hash-lock validation passed.
- Thirty actual local API probes: **30/30 expected security outcomes**; **29/30
  including expected intent routing**. Twenty-six attack/invalid probes were
  rejected or held; four benign probes were not flagged as injection. Password
  reset was incorrectly classified as `exchange_request`; it should be
  unsupported/manual review. See the [complete input/output table](prompt_injection_test_results_2026-11-18.md)
  and [exact JSON responses](prompt_injection_test_results_2026-11-18.json).

The HTTP probes first used an isolated test server, then were repeated against
the restarted application on port 8000 with actual in-process Laya classification.
No API/classifier responses were mocked. The same results were observed in both
runs. These are classification/input-rejection results,
not live order mutations, full RAG attacks, or a production penetration test.
The offline suite additionally exercises poisoned policy/order/communication
evidence, stored tickets, encoded-secret checkpointing, legacy checkpoint resume,
output validation and deterministic response fallback.

## Commands

```bash
./.venv-multi/bin/python scripts/check_dependency_sources.py
./.venv-multi/bin/python -m pip check
./.venv-multi/bin/python -m unittest tests.security.test_sanitization tests.security.test_dependency_sources tests.unit.test_groq_response tests.unit.test_compact_order_workflow tests.unit.test_model_safety_gate tests.unit.test_workflow_optimizations -v
./.venv-multi/bin/python scripts/test_prompt_injection.py --base-url http://127.0.0.1:8000
./.venv-multi/bin/python -m pytest -q
```

The 30-probe script intentionally returns a nonzero exit status for the observed
password-reset intent mismatch, while separately reporting security results.

## Existing full-suite failures

Before implementation, unittest discovery ran 90 tests with 9 failure entries
(including 3 model-safety subtests affected by shared cache state) and 6 errors.
The model-safety tests now isolate cached inputs and unrelated background warmup
calls. The full pytest run has **109 passed, 12 failed**, plus 78 passing subtests.
All twelve failing test cases were already failing in the baseline:

| Test file | Existing failing tests |
|---|---|
| `tests/agents/test_day5_workflow.py` | `test_consequential_proposal_interrupts_then_approves_simulation_only` |
| `tests/api/test_day4_api.py` | `test_low_confidence_classification_is_marked_for_review_and_extracts_order_id` |
| `tests/api/test_rag_evaluation_api.py` | `test_labeled_set_runs_default_eleven_cases` |
| `tests/integration/test_day4_mcp.py` | `test_tools_are_discoverable_and_classifier_returns_structured_result` |
| `tests/unit/test_day2_preparation.py` | `test_classifier_holdout_is_disjoint_and_balanced`; `test_demo_knowledge_documents_are_versioned_and_development_only`; `test_manifest_tracks_current_sources_and_output_counts`; `test_ticket_order_map_keeps_missing_references_unmapped` |
| `tests/unit/test_day3_baselines.py` | `test_only_versioned_synthetic_dev_documents_are_chunked`; `test_semantic_search_filter_is_restricted_to_development_drafts` |
| `tests/unit/test_day4_repositories.py` | `test_order_summary_uses_allowlisted_columns_and_read_only_session`; `test_ticket_query_does_not_select_evaluation_labels` |

The existing failures concern outdated fixture/evaluation expectations, stale
repository test doubles, and mocked integration paths that reach external
workflow storage. They are not evidence of a green full application suite.

## Review and limits

An independent review identified quoted/Unicode credential leaks, partial
Authorization redaction, excessive-decoding bypass, overblocking ordinary
authorization complaints, retained partial evidence after tool errors and
reference-style phishing links. Regression tests reproduce these cases and pass
with the fixes. Older checkpoints are rescreened before rules/proposals/approval.

The changes preserve scoped read-only tools, allowlisted routing and separate
human approval; they add no runtime dependencies. Thirty prompts do not establish
immunity to all attacks. Multilingual/novel encodings, authentication deployment,
denial-of-service resistance, package/model provenance and container image
security require continuing validation. No code has been committed or deployed
to a remote environment.
