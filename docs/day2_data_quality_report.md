# Day 2 Data Quality and Database Check

## Scope and access

Neon and Milvus were inspected with read-only transactions and metadata-only queries. No records were written, changed, or deleted. The local preparation script reads the fictional CSV fixtures under data/raw/ and the generated synthetic support-context CSVs under data/synthetic/, then writes outputs under data/processed/ and the ticket mapping under data/synthetic/.

## Neon Postgres

The connected database is neondb and has nine public tables:

| Table | Rows | Result |
| --- | ---: | --- |
| customers | 1,000 | Unique customer IDs; required IDs present |
| orders | 1,000 | Unique order IDs; all IDs match the generated fixture pattern |
| order_items | 1,248 | Unique item IDs; all product names/categories and order references present |
| delivery_events | 4,866 | Unique event IDs; all order references present |
| returns_refunds | 231 | Unique return IDs; all order/item references present |
| tickets | 1,000 | Unique ticket IDs; all messages and legacy labels present |
| evaluation_cases | 8 | Unique case IDs; every ticket reference resolves |
| policy_sources | 10 | Unique source IDs |
| policy_evidence | 10 | Unique evidence IDs; every source reference resolves |

All 1,000 email values use the reserved customers.example domain. No customer names or email addresses were exported into the cleaned samples.

All checked joins had zero orphan records: orders-to-customers, items-to-orders, delivery-events-to-orders, returns-to-orders/items, tickets-to-orders where a reference exists, evaluation-cases-to-tickets, and evidence-to-policy-sources. Two tickets have no order reference and are preserved as explicitly unmapped. The database has primary keys on the nine tables but no declared foreign-key constraints; current join integrity is data-level only.

The original fixture snapshot used one marketplace, Amazon.in, five order statuses, and 25 legacy ticket labels. The labels included 22 business-intent names plus ambiguous_request, prompt_injection, and unauthorised_data_request routing/security labels. The local preparation extension described below adds three loyalty labels. `general_policy` and `compensation_request` still have too few independent examples for the baseline evaluation set.

Product records are embedded in order_items; there is no separate product table. The clean product catalog is derived from product_id, name, category, and observed order-line prices. Those prices are labeled historical order-line prices, not current catalog prices. The raw return_eligibility field is excluded from cleaned output because it is not backed by a versioned, approved policy.

The policy_sources.verification_status field contains free-form source notes rather than a normalized approval status. The processed review file preserves each note and sets publication_status to review_required; the Amazon.com source is excluded from this Amazon.in fixture.

## Milvus policy collection

The collection marketplace_policy_knowledge_base contains 31 vectors, a 384-dimensional vector field, and an index on that field. Metadata covers 11 document IDs: nine expected policy documents, one excluded Amazon.com reference, and one unexpected record.

The unexpected record is chunk_id 8lkckos6aar, document_id ay2sb8sobw6, marketplace t2lfzlozdpj, page 89, with is_excluded=true. Quarantine it and confirm its origin before using or rebuilding the collection.

The collection schema has chunk_id, vector, document_id, marketplace, page_number, is_excluded, and content. It has no policy ID/version, lifecycle status, effective dates, jurisdiction, locale, or content hash. Therefore the existing index is useful as a retrieval snapshot but cannot provide version-correct policy evidence. The new synthetic demo policies remain draft, development-only files and must not be inserted into this collection.

## Read-only retrieval benchmark

The existing ten-query benchmark was embedded with the locally cached all-MiniLM-L6-v2 model and searched against Milvus with marketplace and exclusion filters:

| Metric | Result |
| --- | ---: |
| Expected document at rank 1 | 9/10 |
| Expected document in top 3 | 9/10 |
| Exact expected document and page at rank 1 | 8/10 |

One mixer-return query returned seller-replacement documents instead of the labeled general returns document. One clothing return-window query found the expected document at rank 1 but returned page 1 while the label expects page 2; page 2 appeared lower in the top results. Review both labels and add category/section metadata before treating page-level accuracy as settled.

## Day 2 artifacts

The output of scripts/prepare_data.py includes normalized operational samples, a derived product catalog, a balanced intent evaluation set across sufficiently represented business labels, a separate eight-case workflow/security set, ten labeled retrieval questions, a policy-source review queue, and a complete ticket/order mapping with unmapped cases retained.

Five versioned policy/FAQ/escalation artifacts are stored under knowledge_base/: three policy drafts, one FAQ, and one escalation rule. They are marked synthetic, draft, and development-only. They specify safe workflow behavior and make no real retailer eligibility or refund promises.

The synthetic ticket/order map is generated from each ticket's explicit `order_id` field. Tickets with a blank reference stay in the map with `unmapped_missing_order_reference`; the preparation step does not guess a matching order.

## Local customer-context extension (2026-11-06)

The local generator added 1,000 fictional loyalty account snapshots, 816 ledger events, 1,333 PII-minimized prior-contact summaries, and 180 loyalty tickets (60 each for `loyalty_points`, `reward_expiry`, and `reward_redemption`). The prepared manifest reports 1,180 tickets in total and two explicitly unmapped tickets. Ledger balances reconcile against posted transactions; account/customer/order references are checked; direct email and phone patterns are rejected from communication summaries. The generator is repeatable and only rebuilds ticket IDs in its own `T-CTX-*` namespace.

The classifier evaluation split now groups by linked customer and normalized message template. On the refreshed 46-case synthetic holdout, the TF-IDF fallback scored 0.913 accuracy and 0.894 macro-F1. This result is more isolated than the previous random row split, but still uses templated fictional language and does not establish real-ticket performance. The earlier live Laya result (18/40 correct, 0.418 macro-F1) remains the last measured Laya result; `scripts/evaluate_laya_classifier.py` can rerun Laya on the refreshed holdout when its local service is available.

Migration `backend/app/db/migrations/002_customer_support_context.sql` adds three context tables. It has not been applied to Neon, and the local seed script has not written any database rows. Use only a dedicated development branch after reviewing the migration and setting the explicit seed opt-in documented in the root README.

## Remaining data controls

- Add foreign-key and check constraints through reviewed migrations after validating the migration on a non-production Neon branch.
- Normalize source review state, dates, and policy version metadata in the policy registry.
- Quarantine the unexpected Milvus chunk and rebuild from approved, versioned documents with scope metadata and hashes.
- Collect more general_policy and compensation_request examples before evaluating those model classes.
- Have policy, data, and security owners approve any production source, policy, identity, retention, or access decisions before enabling production use.
