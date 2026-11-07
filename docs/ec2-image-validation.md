# EC2 image validation — 2026-11-07

## Scope

One x86_64 API process, English Laya, MiniLM, CPU-only inference. The
Streamlit frontend remains external. Durable workflow workers and approvals
are outside the selected demo deployment.

## Checks

- Existing saved image: 887,617,073 bytes (Docker metadata); CPU-only PyTorch
  2.15.0+cpu, Laya 0.4.27, sentence-transformers 6.2.0.
- Reproduced the old image failing offline inference with LocalEntryNotFoundError
  because the Laya checkpoint was not cached.
- Main Dockerfile static check: passed with no warnings after correcting the
  install/cleanup shell chain so installation errors cannot be swallowed.
- Mac image build: passed, including pip check (no broken requirements).
  Built for linux/amd64 using the cached pinned Laya checkpoint and digest-pinned
  dependency base. Mac Docker reported 1,665,769,586 bytes; do not use this as
  the native host's uncompressed storage estimate.
- Mac offline check: passed with networking disabled, two CPUs, and a hard 3-GiB
  memory limit with no swap. Provider laya, fallback false, damaged_item for the
  sample message, a normalized 384-value embedding, and both HTTP checks passed.
  Container peak: 2,369.8 MiB. Reported process max RSS under emulation:
  3,101.3 MiB. The cgroup memory limit was enforced for the whole container.
- A second run also passed the same 3-GiB limit (container peak 2,528.1 MiB).
  Three further unseen messages all used Laya and took 3.688, 3.646, and
  3.461 seconds with the model already loaded. These are emulation measurements,
  not promises of EC2 query speed.
- First classification including model loading: 7.649 seconds; repeated cached
  classification: 0.000006 seconds. These are measurements under x86 emulation
  on the Mac, not native EC2 latency predictions or an accuracy evaluation.
- The SDK warns that some checkpoint temperature entries are invalid and are
  clamped. Classification confidence remains uncalibrated and human review
  remains required by the application's existing routing policy.

## Native EC2 verification

- Source build on the selected Ubuntu x86_64 instance: passed. The base image
  and pinned checkpoint downloaded directly on EC2, avoiding the slow upload
  from the Mac. No dependency installation was needed; pip check passed.
- Native Docker image size: **4,448,392,855 bytes**. The compressed transfer
  archive was 1,663,509,110 bytes. These are different storage measurements.
  After the native build, the 24-GiB root filesystem had about 14 GiB free.
- Offline smoke check under the 3-GiB hard limit: passed. CPU-only PyTorch,
  provider `laya`, fallback false, MiniLM dimension 384. First classification
  including loading: 6.839 seconds; container peak 2,910.5 MiB. Three unseen
  warm classifications took 2.009, 2.023, and 2.021 seconds. PyTorch reported
  one thread. Steady API memory after live requests was about 2.14 GiB.
- Private API checks: health, ticket lookup, keyword search, semantic search,
  and the 12-case semantic-plus-keyword evaluation returned HTTP 200. The
  labeled batch took 4.241 seconds, versus the old Render HTTP 504 at 31.57s.
- Public HTTPS at `https://3.27.207.159`: normal certificate verification
  passed. Missing or incorrect gateway tokens returned HTTP 401. Correct-token
  classification returned HTTP 200, provider `laya`, fallback false, in 3.725s.
- Full ticket T-003 investigation over HTTPS: HTTP 200 in 5.263s, provider
  `laya`, fallback false, evidence found, order and customer context present,
  both semantic and keyword results. An earlier first attempt returned HTTP
  503; subsequent attempts succeeded. Its transient dependency failure has
  not been diagnosed, so these results do not establish sustained reliability.
- Frontend request-contract and token-destination tests: all four passed for
  both the working frontend and the minimal patch prepared from GitHub main.
  The live Streamlit migration still requires publishing that patch and
  updating Streamlit secrets; a passing API check does not prove that step.
- Serving Laya does not establish model accuracy. One live damaged-item
  paraphrase was classified as partial delivery; retain human review and do
  not infer that changing hosts fixes routing quality.

## Transfer fallback

The initial Mac upload was too slow (about 48 MB of 1.66 GB after roughly ten
minutes). The standalone EC2 Dockerfile now downloads the existing base layers
and the pinned checkpoint directly; the separately preserved local build file
reproduces the already-tested image build.

## Broader application regression suite

Command:

```bash
APP_ENV=local LANGFUSE_TRACING_ENABLED=false LLM_ENABLED=false \
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 .venv-multi/bin/python \
  -m unittest discover -s tests -p 'test*.py'
```

Result: **86 tests run; 9 failures and 6 errors**. No application runtime code
was changed for this image work. These unresolved failures include stale
fixture counts, dependency/API assumptions, and classification-cache test
isolation. They prevent claiming that the full project suite passes.

- `ERROR: test_consequential_proposal_interrupts_then_approves_simulation_only (agents.test_day5_workflow.Day5WorkflowTests.test_consequential_proposal_interrupts_then_approves_simulation_only)`
  - WorkflowStoreUnavailable: workflow database operation failed during the approval simulation test.
- `ERROR: test_tools_are_discoverable_and_classifier_returns_structured_result (integration.test_day4_mcp.Day4McpTests.test_tools_are_discoverable_and_classifier_returns_structured_result)`
  - The MCP expected-tool list omits get_customer_support_context, which is returned by the server.
- `ERROR: test_manifest_tracks_current_sources_and_output_counts (unit.test_day2_preparation.Day2PreparationTests.test_manifest_tracks_current_sources_and_output_counts)`
  - FileNotFoundError: [Errno 2] No such file or directory: '/Users/adityapathania/Codes/bz/Agentic_Customer_Experience_Supply_Chain_Resolution/data/raw/data/raw/customers.csv'
- `ERROR: test_semantic_search_filter_is_restricted_to_development_drafts (unit.test_day3_baselines.Day3BaselineTests.test_semantic_search_filter_is_restricted_to_development_drafts)`
  - TypeError: MilvusPolicyRetriever._filter() missing 1 required positional argument: 'locale'
- `ERROR: test_order_summary_uses_allowlisted_columns_and_read_only_session (unit.test_day4_repositories.Day4RepositoryTests.test_order_summary_uses_allowlisted_columns_and_read_only_session)`
  - AttributeError: module 'backend.app.db.session' has no attribute 'psycopg2'
- `ERROR: test_ticket_query_does_not_select_evaluation_labels (unit.test_day4_repositories.Day4RepositoryTests.test_ticket_query_does_not_select_evaluation_labels)`
  - AttributeError: module 'backend.app.db.session' has no attribute 'psycopg2'
- `FAIL: test_low_confidence_classification_is_marked_for_review_and_extracts_order_id (api.test_day4_api.Day4ApiTests.test_low_confidence_classification_is_marked_for_review_and_extracts_order_id)`
  - AssertionError: 'possible_instruction_override' not found in ['model_safety_check_not_passed', 'low_classifier_confidence', 'laya_unavailable_baseline_fallback']
- `FAIL: test_labeled_set_runs_default_eleven_cases (api.test_rag_evaluation_api.RagEvaluationApiTests.test_labeled_set_runs_default_eleven_cases)`
  - AssertionError: 12 != 11
- `FAIL: test_classifier_holdout_is_disjoint_and_balanced (unit.test_day2_preparation.Day2PreparationTests.test_classifier_holdout_is_disjoint_and_balanced)`
  - AssertionError: 46 != 40
- `FAIL: test_demo_knowledge_documents_are_versioned_and_development_only (unit.test_day2_preparation.Day2PreparationTests.test_demo_knowledge_documents_are_versioned_and_development_only)`
  - AssertionError: 6 != 5
- `FAIL: test_ticket_order_map_keeps_missing_references_unmapped (unit.test_day2_preparation.Day2PreparationTests.test_ticket_order_map_keeps_missing_references_unmapped)`
  - AssertionError: 1180 != 1000
- `FAIL: test_only_versioned_synthetic_dev_documents_are_chunked (unit.test_day3_baselines.Day3BaselineTests.test_only_versioned_synthetic_dev_documents_are_chunked)`
  - AssertionError: 6 != 5
- `FAIL: test_unsafe_uncertain_or_invalid_verdict_stops_before_intent (unit.test_model_safety_gate.ModelSafetyGateTests.test_unsafe_uncertain_or_invalid_verdict_stops_before_intent) (answer={})`
  - AssertionError: True is not false
- `FAIL: test_unsafe_uncertain_or_invalid_verdict_stops_before_intent (unit.test_model_safety_gate.ModelSafetyGateTests.test_unsafe_uncertain_or_invalid_verdict_stops_before_intent) (answer={'type': 'choice', 'choice': 'unsafe_or_uncertain', 'answer_confidence': 0.99})`
  - AssertionError: True is not false
- `FAIL: test_unsafe_uncertain_or_invalid_verdict_stops_before_intent (unit.test_model_safety_gate.ModelSafetyGateTests.test_unsafe_uncertain_or_invalid_verdict_stops_before_intent) (answer={'type': 'choice', 'choice': 'safe_support_request', 'answer_confidence': 0.5})`
  - AssertionError: True is not false
