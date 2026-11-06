# Data Directory

## Directory rules

- raw/: immutable input fixtures and source extracts. Record source, capture time, licence/provenance, and schema.
- processed/: deterministic cleaned and normalized outputs. Record source hashes, transformation version, row counts, and validation results in a manifest.
- synthetic/: generated tickets, mappings, and evaluation-only records. Preserve generation seed/version and synthetic provenance in metadata.

Do not overwrite raw inputs during cleaning. Do not place production customer exports in this repository. The files currently under raw/ are generated fictional fixtures, not real customer or order records.

## Current fixture

The raw fixture joins customers, orders, order items, delivery events, return/refund records, and tickets through explicit opaque IDs. The ticket labels are in expected_intent; that field mixes business intents with triage/security outcomes. Synthetic loyalty accounts, ledger events, prior-contact summaries, and loyalty tickets are generated under synthetic/ and never appended to raw/. See docs/intent_taxonomy.md for the taxonomy.

The current evaluation_cases.csv contains eight workflow/security cases. It is not a sufficient held-out classifier or retrieval benchmark.

## Day 2 prepared outputs

Run scripts/generate_support_context_fixtures.py and then scripts/prepare_data.py from the project root after the Python environment is installed. The generator writes synthetic inputs under synthetic/; preparation reads those plus immutable raw/ fixtures and writes clean samples to processed/ along with the explicit synthetic ticket/order mapping.

The preparation produces clean order, order-item, product-catalog, delivery-event, return/refund, loyalty-account, loyalty-transaction, and customer-communication CSVs; a customer/template-grouped classifier train/evaluation split; a separate workflow/security set; a retrieval benchmark; a normalized policy-source review queue; and data_quality_manifest.json. It omits customer names/emails and does not copy the unverified return_eligibility field into clean order items.

The current retrieval labels do not include policy versions because the connected Milvus collection has no version metadata. This limitation is recorded in processed/retrieval_evaluation.csv and docs/day2_data_quality_report.md.

Day 3 adds a separate labeled set, processed/rag_policy_evaluation_v1.csv, for the versioned synthetic development documents. It currently includes a new loyalty-policy case. The chunk output and semantic/keyword retrieval metrics are written under processed/; the trained model artifact stays under the ignored models/ directory.

## Production data gate

Before adding production-source data, document the source-system owner, permitted fields, access method, jurisdiction, purpose, freshness, retention, deletion, and incident contact. Use an authorized read-only view/API and minimize replicated fields. Do not join unrelated datasets by guessing.
