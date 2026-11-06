# Day 3 Baseline Evaluation

## Scope

This report evaluates local fictional ticket data and six synthetic policy/FAQ/escalation documents. The policy documents are version `1.0.0`, status `draft`, and scoped to `development-only`. These measurements do not establish production suitability or retailer policy accuracy.

## Intent classification

The offline baseline is word unigram/bigram TF-IDF with logistic regression. After adding synthetic loyalty examples and changing the holdout to isolate linked customers and normalized duplicate message templates, it trained on 944 rows and evaluated on 46 held-out examples across 23 labels (two examples per label). Runtime classification calls Laya first; this baseline remains an explicit review-only fallback when Laya is unavailable.

| Metric | Result |
| --- | ---: |
| Accuracy | 0.913 |
| Macro F1 | 0.894 |
| Weighted F1 | 0.894 |

These results are still optimistic because the fixture uses templated synthetic language. They do not establish accuracy on real tickets. `general_policy` and `compensation_request` lack enough independent groups and are excluded from this baseline's evaluation. Probabilities are not calibrated. Laya's last measured result on the earlier 40-case set was 18/40 correct (45%) with macro-F1 0.418, including high-confidence errors. The refreshed Laya evaluation has not been run; use `scripts/evaluate_laya_classifier.py` with the local Laya service. Runtime routing requires strict Laya/TF-IDF consensus, and the opt-in remains disabled by default.

Outputs are `data/processed/intent_baseline_metrics_v1.json`, `intent_predictions_v1.csv`, and `intent_confusion_matrix_v1.csv`. The local model artifact is written to `models/intent_tfidf_logreg_v1.joblib` and is ignored by Git.

## Policy chunks and Milvus

The chunker reads only the six versioned files under `knowledge_base/` and emits 22 section-aware passages. The FAQ and return-eligibility draft include a damage-specific section for reports of damaged, broken, or defective items. A loyalty/rewards draft provides ledger lookup guidance. Each chunk includes document ID, policy version, draft status, development scope, marketplace, jurisdiction, locale, intent/category metadata, source-file SHA-256, section ID/title, and excerpt text. Synthetic Markdown policies/FAQ are split on headings; the escalation YAML emits one passage per condition.

Embeddings use `sentence-transformers/all-MiniLM-L6-v2` (384 dimensions). Milvus stores the vectors and scalar metadata in `agentic_customer_support_dev_policies_v1`. The local chunk files contain 22 passages across six documents. The Milvus collection has not yet been refreshed with the new loyalty document; all source files remain `draft` and `development-only`. Reindex the separate development collection and rerun evaluation before reporting a 12-query retrieval score.

The existing `marketplace_policy_knowledge_base` collection remains unchanged at 31 rows. It still lacks the version/lifecycle fields described in [Day 2's database check](day2_data_quality_report.md), so it is not used by this version-aware pipeline.

## Retrieval benchmark

Eleven manually labeled questions were previously evaluated against the five-document synthetic development corpus, including “What should I do if my order is damaged?” A twelfth labeled synthetic loyalty question has since been added. The published 11-query results below predate that policy and must not be described as a refreshed 12-query result. A local TF-IDF keyword baseline and semantic Milvus search use the same chunks and scope. Hit@K is based on expected document ID; section accuracy requires the expected document and section at rank 1.

| Metric | TF-IDF keyword | Milvus semantic |
| --- | ---: | ---: |
| Expected document Hit@1 | 8/11 (73%) | 8/11 (73%) |
| Expected document Hit@3 | 11/11 (100%) | 11/11 (100%) |
| MRR@3 | 0.848 | 0.833 |
| Expected section at rank 1 | 7/11 (64%) | 7/11 (64%) |
| Scope compliance | 100% | 100% |
| Citation metadata complete | 100% | 100% |

For the damaged-order query, both methods return `DEMO-SUPPORT-FAQ` section `My item arrived damaged` at rank 1. Across the earlier 11-case set, both methods found every expected document in the top three; results on this small synthetic corpus do not establish production suitability. Keep the rank and excerpt visible to reviewers and expand the labels with policy-owner-reviewed examples before using retrieval results for customer responses.

Evaluation details are in `data/processed/rag_retrieval_metrics_v1.json` and `rag_retrieval_predictions_v1.csv`. The query labels are in `data/processed/rag_policy_evaluation_v1.csv`.

## Reproduction

From the repository root, after installing `requirements.txt` and setting the Milvus URI/token in the ignored local `.env`:

```bash
./.venv-multi/bin/python scripts/generate_support_context_fixtures.py
./.venv-multi/bin/python scripts/prepare_data.py
./.venv-multi/bin/python scripts/train_classifier.py
APP_ENV=local ./.venv-multi/bin/python scripts/evaluate_laya_classifier.py
./.venv-multi/bin/python scripts/chunk_versioned_policies.py
EMBEDDING_MODEL=sentence-transformers/all-MiniLM-L6-v2 ./.venv-multi/bin/python scripts/index_dev_policies.py
EMBEDDING_MODEL=sentence-transformers/all-MiniLM-L6-v2 ./.venv-multi/bin/python scripts/evaluate_day3_rag.py
```

The indexer refuses non-development collection names, creates the isolated collection if absent, and upserts stable chunk IDs. It never drops the existing collection. Retrieval requires `status=draft`, `environment_scope=development-only`, `synthetic_demo=true`, and matching marketplace and locale. The added loyalty chunk is local only until that explicit Milvus indexing command is run.
