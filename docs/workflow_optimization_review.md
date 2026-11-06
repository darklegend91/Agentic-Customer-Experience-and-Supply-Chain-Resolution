# Investigation performance and safety review — 2026-11-06

The reported order-status request was escalated before any order tool ran.
Automatic model routing was disabled, and Laya disagreed with the TF-IDF
baseline. The UI's raw probability was incorrectly presented as confidence
without explaining that it was uncalibrated. A conditional Streamlit expression
also caused the framework's object help to appear in the result panel.

## Processing order

1. Validate arguments and caller ticket/order scope.
2. Normalize text and mask sensitive contact/payment values before model input.
3. Run Laya's typed input-safety assessment, without giving the model tools.
4. Reject unsafe, low-score or malformed safety results; keep deterministic
   injection/approval-bypass checks as an additional boundary. A permissive model
   cannot override those checks. Model failure cannot enable automatic routing.
5. Classify intent only after the safety assessment passes. A whole-message
   rule recognizes a narrow set of explicit order-status questions after this
   model gate. Extra clauses and mixed requests do not match the rule.
6. Read scoped records, validate the evidence and produce cited facts. Status
   questions do not need policy retrieval or optional loyalty/contact lookups.
7. Consequential requests retain deterministic eligibility checks and approval.

This deployment uses Laya, a typed decision model, for the model assessment.
It does not have a separate generative security LLM configured. Neither model
screening nor keyword checks guarantee detection of all prompt injections.
Tool isolation, authorization, deterministic rules and approval remain required.

## Changes and measurements

* Workflow writes and reads reuse a bounded PostgreSQL connection pool. Each
  operation still has its own committing/rolling-back transaction and local SQL
  timeout; approval operations are not cached.
* A single authorized `GET /workflows/{id}/snapshot` replaces three UI requests.
  While running, progress uses audit events without repeatedly loading the full
  checkpoint. Completed snapshots include the checkpoint evidence. Existing
  status, trace and event endpoints remain available.
* Streamlit reuses an HTTP client; settled results remain in session state.
  The result renderer uses explicit statements and labels scores as uncalibrated.
* Three trivial database reads before pooling took 10.009, 8.725 and 3.876 s.
  With pooling, the first connection took 6.724 s and three warm operations took
  1.173, 1.631 and 1.221 s. These are small local measurements against the same
  remote database, not a load-test guarantee.
* A warm local model safety-plus-intent call for a status request took 0.629 s.
  A cold call took 14.336 s. Keeping a model process warm matters.
* A live investigation for `ORD-ID-022d195439` returned `answer_ready`, citing
  the SQL record's `delivered` status. The persisted workflow took 37.05 s from
  queue intake to completion. Checkpoint and database network latency remains;
  the full workflow is not a sub-second lookup.

## Accuracy and validation limits

The refreshed 46-case synthetic Laya holdout scored 20/46 (43.48%) intent
accuracy and macro F1 0.395 after the follow-up fixes below. There were still 19
wrong accepted predictions above the model threshold. General autonomous model
routing therefore remains disabled. This patch improves a bounded status flow;
it does not establish reliable accuracy across all intents or security attacks.
The measured outputs are `data/processed/laya_intent_evaluation_v1.json` and
`data/processed/laya_intent_predictions_v1.csv`.

Focused regression tests cover model safety before intent, masking, unsafe and
uncertain decisions, mixed requests, cited status facts, pooled transaction
release and snapshot authorization. The full legacy suite still contains stale
fixtures/mocks (old dataset counts, removed synchronous workflow dispatch,
unpooled repository mocks, and policy fixtures that fail current approval
requirements). It must not be reported as fully passing.

The running Streamlit app was exercised through its agent API and produced an
Answer Ready result without the internal object dump. Browser automation was
unavailable because local browser use is disabled in Codex Work settings.

## Follow-up: false security flags and missing chat context

The three reported runs had different causes:

* `b8de9565…` used the older classification path: model disagreement stopped
  investigation, although the old fallback incorrectly mentioned missing policy.
* `28e9a472…` failed with a PostgreSQL `OperationalError` before input processing.
  The execution wrapper had swallowed this error and permanently failed the run,
  preventing the existing durable retry queue from recovering it.
* `758dfb7b…` rejected an ordinary order-details request in the model safety gate.
  Laya's automatic language selection repeatedly switched between English and
  multilingual checkpoints for short English questions with opaque identifiers.

The classifier now substitutes only recognized ten-hex-digit order references
in model input with an order description. Surrounding untrusted instructions
remain visible to the safety model; original entities remain subject to backend
scope validation. English is the router default for ambiguous short text, while
detected non-English text still uses the multilingual route. Safety rejection
still blocks investigation. Whole-message read-only rules now include order
details and order-ID questions; mixed requests still require triage.

The frontend carries only the last order reference between turns, sends the new
message through safety screening, and performs a fresh lookup. A new explicit ID
replaces inferred context; multiple IDs remain ambiguous. Clear chat removes the
inferred reference, and changing API/token clears cached conversation/evidence.
The UI updates completed runs instead of leaving their chat status as running.

Transient database failures now reach the bounded worker retry mechanism, which
resumes pending checkpoints. First attempts avoid an unnecessary checkpoint read.
Checkpointer connections use autocommit and prepared statements. Audit-only
transactions pipeline BEGIN, timeout, INSERT and COMMIT; errors remain fatal to
the attempt and trigger retry. Approval transactions retain their existing path.

Validation: 22 focused tests pass, including safety ordering, scoped snapshots,
conversation references, checkpoint resume and audit-flush errors. The edited
frontend, classifier, worker and persistence/service modules pass `ty`. Checking
the graph module also surfaced pre-existing TypedDict/generic annotation errors;
the repository is not claimed to be globally type-clean or fully test-clean.

All 14 targeted routing regressions behaved as expected: six ordinary questions
were admitted after model screening; five injection attempts and three mixed or
disputed requests did not enter the status-only path. This is a targeted regression
set, not an overall accuracy estimate. Results are in
`data/processed/order_chat_routing_evaluation.json`.

The independent 46-case intent holdout still scored 20/46 (43.48%). Its macro F1
is 0.395 and average call latency, including cold startup, was 0.802 seconds.
General model routing remains disabled. Warm checks in the targeted set took
0.27–0.81 seconds; previously model swaps took about 11–12 seconds each.

The real Streamlit agent API successfully completed `tell me about
ORD-ID-022d195439` and the follow-up `tell me about this order and what is my order
id ?`, both returning the ID and the SQL record's `delivered` status with evidence.
Before audit pipelining those workflows took 41.24 seconds cold and 25.80 seconds
warm. After pipelining, the first cold run took 35.69 seconds and the warm
follow-up took 25.29 seconds. This does not demonstrate a meaningful end-to-end
speedup from pipelining alone. Remote SQL and
checkpoint latency remains significant; these are individual local observations,
not load-test guarantees or sub-second end-to-end response claims.

## Consolidated checkpoints and monitoring — 2026-11-07

The bounded order-status path now uses three checkpointed steps instead of nine:
assess the request, investigate/validate the read-only answer, and finalize.
Every safety, scope, evidence and output check still executes. Audit entries keep
their individual timestamps and commit in two batches. An interrupted read-only
node can replay safely; consequential paths retain their proposal and approval
interrupt nodes. Old node names remain available for existing checkpoints.

Completed answers persist a minimized presentation snapshot alongside the workflow
summary, eliminating a second checkpoint load when the authorized UI displays
the result. The response now reads: "Your order ORD-ID-022d195439 is marked as
delivered. If it hasn’t arrived, please let us know." Citations and action
boundaries remain in the structured response and application controls.

Two consecutive local benchmark pairs measured 28.18/14.44 seconds and
27.23/13.39 seconds (cold/warm). The warm path previously measured 25.29 seconds.
The first request after a process restart still pays model/connection startup
costs. These observations establish a local improvement, not a latency SLA.

Langfuse SDK 5.2 monitoring now exports asynchronously to the configured
Agentic_support project. Workflow/session IDs link the root trace and child spans.
The live workflow `238fe142-3303-4188-b85b-12d0887bef85` produced 12 observations
in trace `ed57fb74a72068c47d6c06f552581064`, verified through Observations API v2.
Its safety call took 0.605 s, intent call 0.117 s and order lookup 3.522 s.
Raw messages, customer records, answers and credentials are omitted from trace
payloads; actor subjects are hashed. Monitoring cannot authorize actions, and
export failures do not block the support workflow. Explicit flushes occur only
at shutdown or in verification scripts.

33 focused tests pass, including approval interrupts, checkpoint consolidation, complete audit batches,
completed-snapshot reuse, supported SDK arguments, masking and telemetry failure
isolation. Edited monitoring/service modules pass type checks; the graph retains
one pre-existing LangGraph TypedDict generic-bound checker diagnostic. Legacy
suite limitations described above remain.
