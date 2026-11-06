# Data scale and policy capture design

## Intent

Expand the project's existing fictional marketplace support fixture so it supports larger, more varied customer-support demonstrations while retaining coherent joins and the existing security and policy edge cases. Collect local PDF files for every policy source URL currently listed in `data/policy_sources.csv` so the documents can be chunked later.

## Goals

- Generate 1,000 customers, 1,000 orders, and 1,000 tickets from the existing deterministic generator.
- Vary customer attributes, order timing/status, products, quantities/prices, locations, event sequences, ticket phrasing/intents, and return/refund outcomes.
- Preserve existing hand-authored evaluation edge cases and keep evaluation references valid.
- Remove the word `synthetic` from CSV filenames and cell values. Keep fictional provenance explicit in README/documentation.
- Replace sequential `IN-DEMO` order IDs with unique, regex-valid demo-safe IDs. Proposed format: `ORD-ID-` followed by 10 lowercase alphanumeric characters, generated deterministically.
- Capture each URL in the existing policy source registry as a PDF: use the publisher's PDF when available; otherwise render/save the official source page as a PDF. Keep the Amazon.com source marked excluded in the registry and keep its PDF in a clearly separate excluded-reference directory.
- Record source URL, capture date, capture method, and success/failure in a manifest. Do not turn PDFs into chunks or add policy claims to the evidence CSV.

## Non-goals and guardrails

- These records remain fictional demo data. Removing a label from CSV rows must not imply that the records are real customer or transaction data.
- Do not use public commerce data or personal data.
- Do not infer policy eligibility from a saved page, alter policy summaries, or treat a saved page as a validated policy snapshot.
- Do not chunk or embed the PDFs in this change.

## Approaches considered

1. Expand the established deterministic fixture generator (selected). This preserves the project's Amazon.in support scope, keeps existing evaluation cases meaningful, and gives repeatable larger data.
2. Add a public retail dataset. This would add real historical variation, but it would bring unrelated geography and licensing constraints and would not supply verified support tickets. It was declined.

## Design

The generator will own the customer table and write consistently named CSVs without `synthetic` in their filenames. Each customer gets one primary order and linked ticket for simple coverage, with the data generator allowing varying order-item, delivery-event, return, and refund cardinalities. Existing special tickets and evaluation cases remain pinned to their original case IDs and are remapped to the new order-ID format. Other rows are generated from a balanced set of product/category, intent, resolution, date, seller, and city distributions, with deterministic variation in message wording and values rather than a short repeated template cycle.

Order IDs use `^ORD-ID-[a-z0-9]{10}$`; customer, ticket, item, product, event, and return identifiers use similarly consistent, unique, demo-safe formats. IDs and foreign keys are validated by the generator before writing output.

Policy capture uses the source URLs already present in `policy_sources.csv`, de-duplicating repeated URLs while retaining source-ID mappings in a manifest. The generated PDF must be a publisher-provided document when a direct official PDF is available; for HTML sources, save a readable PDF rendering of the official page. The Amazon.com entry remains excluded from retrieval even though its page is captured in the excluded-reference area. Unavailable or blocked pages are recorded as failures rather than replaced with guessed or third-party policy content.

## Validation

- Regenerate all CSVs and confirm exactly 1,000 unique customers, orders, and tickets.
- Check uniqueness and format of identifiers, foreign-key integrity, expected evaluation ticket references, valid dates/statuses, and distributions across the intended categories and intents.
- Search every CSV filename and cell for `synthetic` (case-insensitive); expect no matches.
- Confirm every policy URL has a manifest entry and every successful capture opens as a readable PDF; report unavailable sources explicitly.
- Confirm policy evidence content and marketplace exclusion flags remain unchanged.
