# Dataset and Data Plan

## Selected data for Day 1

The current development fixture is generated fictional marketplace support data. It is the selected source for Day 2 preparation and Day 3 baseline evaluation because its customer, order, ticket, item, event, return, and evaluation references are linked. It is not real operational history and must not be loaded into production.

Project_5.docx recommends Olist as a public historical dataset. This Day 1 implementation instead keeps the repository's linked fictional fixture as the MVP evaluation source, consistent with the existing data-scale plan. This is an explicit scope choice; Olist is not imported, and neither source is a production order system.

The original Neon read-only snapshot contained 1,000 customers, 1,000 orders, 1,000 tickets, 1,248 order items, 4,866 delivery events, 231 return/refund records, and 8 labeled evaluation cases. The local synthetic fixture now adds 1,000 loyalty-account snapshots, 816 loyalty-ledger transactions, 1,333 prior-contact summaries, and 180 loyalty-intent tickets (60 per intent), stored under data/synthetic/. The prepared working set contains 1,180 tickets across 25 business intents and 3 routing/security labels. The original data/raw/ files remain unchanged, and the additional rows have not been written to Neon.

## Current raw tables

| File | Grain and key | Relevant fields | Intended use |
| --- | --- | --- | --- |
| data/raw/customers.csv | One row per customer_id | Generated name/email, location, language, tier, segment, account date | Fixture joins only; restrict access because values are PII-shaped |
| data/raw/orders.csv | One row per order_id | customer_id, status, order/delivery dates, seller, scenario, marketplace | Read-only investigation fixture |
| data/raw/order_items.csv | One row per item_id | order_id, product, category, quantity, price, reported condition | Item-level investigation fixture |
| data/raw/delivery_events.csv | One row per event_id | order_id, event, timestamp, location, source | Delivery timeline fixture |
| data/raw/returns_refunds.csv | One row per return_id | order_id, item_id, request time, return/refund status, source | Return/refund investigation fixture |
| data/raw/tickets.csv | One row per ticket_id | Message, legacy expected intent, order_id, expected handling | Classifier training and triage evaluation |
| data/raw/evaluation_cases.csv | One row per case_id | Ticket reference, expected intent/route/outcome, security tag | Small workflow/security regression set |
| data/raw/policy_sources.csv | One row per source_id | Marketplace, source URL/type, observed date, use, verification status | Policy source registry; not policy approval |
| data/raw/policy_evidence.csv | One row per evidence_id | Topic, summary, source, scope, verification date, automation | Evidence notes; not a substitute for approved policy text |
| data/synthetic/customer_loyalty_accounts.csv | One row per synthetic customer account | Tier, recorded points balance, account status, snapshot time | Local fixture only; balance is checked against posted ledger rows |
| data/synthetic/loyalty_transactions.csv | One row per synthetic event_id | Event type, point delta, status, expiry, reward reference | Local fixture only; no points mutation is supported |
| data/synthetic/customer_communications.csv | One row per synthetic communication_id | Channel, topic, PII-minimized summary, time, outcome | Local fixture only; messages are untrusted evidence |
| data/synthetic/support_context_tickets.csv | 180 synthetic tickets across three loyalty intents | Message, expected intent, mapped order, expected handling | Training/evaluation fixture only |

Validate IDs and joins before use. Never join a ticket to an order by name, email, or guessed customer mapping.

## Production data-source plan

The production order and delivery source has not been identified. Before connecting one, record the system owner, approved fields, access method, freshness guarantees, jurisdiction, purpose, retention, and incident contact.

The production connector must expose only fields required by approved investigation tools. Prefer a read-only service/API or database view over copying an entire commerce database. The support application must not become the authoritative order, payment, refund, or identity system.

The project brief lists Olist as a possible public historical dataset. No Olist data is present here. If it is later used, verify the current source and licence, keep it separate from the fictional fixture, and do not claim it represents live order status or real support history.

## Data handling

- Treat the fixture as generated, but treat names, emails, ticket messages, and order references as sensitive-shaped fields.
- Use generated or pseudonymous identifiers in development and evaluation.
- Redact direct identifiers before sending text to an external model provider.
- Keep raw source files immutable. Write cleaned or mapped outputs to data/processed/ and preserve a transformation manifest.
- Store generated tickets and mappings in data/synthetic/; preserve generated-data provenance in metadata.
- Keep retrieval evaluation separate from training data and record expected document IDs, policy versions, and relevant sections.
- For classifier evaluation, split by customer or order group. Report macro-F1, per-class metrics, and selective-routing behavior.
- The local intent holdout now groups linked customers/orders and normalized duplicate message templates; synthetic records that share a group cannot cross the train/evaluation boundary.
- Agree on retention and deletion rules with the data owner before production launch.

## Policy source handling

Source URLs and evidence summaries are not automatically approved policy. A policy manager must verify source provenance, jurisdiction, marketplace, effective date, and scope before publication. Preserve captured source files and cryptographic hashes. Do not replace an unavailable source with a third-party copy or generated summary.

The captured policy PDFs are now under output/pdf/ within the canonical project tree. Day 2 adds versioned policy artifacts under knowledge_base/; the PDF captures remain source evidence and still need review before policy publication.
