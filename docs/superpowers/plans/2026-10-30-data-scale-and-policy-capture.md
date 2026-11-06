# Data Scale and Policy Capture Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Expand the fictional marketplace support data to 1,000 linked customers, orders, and tickets and save source PDFs for the registered policy URLs.

**Architecture:** Extend the deterministic Python CSV generator and its current output files; preserve evaluation cases and marketplace scoping. Add a source capture manifest and PDF files under `output/pdf/policy_sources/`, keeping the Amazon.com capture separately excluded from policy retrieval.

**Tech Stack:** Python standard library, CSV, official source web pages/PDFs, PDF metadata/text inspection tools already available in the environment.

**Spec:** `../specs/2026-10-30-data-scale-and-policy-capture-design.md`

## Global Constraints

- Generate exactly 1,000 customers, 1,000 orders, and 1,000 tickets.
- Order IDs match `^ORD-ID-[a-z0-9]{10}$`.
- Remove `synthetic` from CSV filenames and cell values; retain fictional provenance in documentation.
- Keep policy evidence summaries and marketplace exclusion semantics unchanged.
- Do not chunk or embed policy PDFs.

## Review Focus

- Missing/duplicate IDs and foreign keys: validate uniqueness and referential integrity after generation.
- Date/status combinations: check all generated dates parse and records with non-shipped states do not claim impossible delivery timelines.
- Evaluation linkage: check all fixed evaluation ticket references still resolve to the intended edge cases.
- Repeated message or attribute cycles: inspect category and intent distributions and sample messages across the full range.
- Blocked/changed policy URLs: manifest every URL, mark failed captures clearly, and never substitute unofficial policy text.

---

### Task 1: Expand the linked fictional fixture

**Files:**
- Modify: `data/generate_demo_data.py`
- Create/modify: `data/customers.csv`, `data/orders.csv`, `data/order_items.csv`, `data/delivery_events.csv`, `data/returns_refunds.csv`, `data/tickets.csv`, `data/evaluation_cases.csv`, `data/policy_sources.csv`, `data/policy_evidence.csv`
- Remove obsolete generated names: `data/synthetic_*.csv`
- Modify: `data/README.md`

**Interfaces:**
- Generator remains runnable with `python3 data/generate_demo_data.py` and deterministic from a fixed seed.
- CSV foreign keys use the new demo-safe IDs.

- [x] Replace sequential ID generation with the specified deterministic demo-safe formats, retaining the first 20 edge-case ticket messages and their evaluation links.
- [x] Generate 1,000 distinct customer/order/ticket rows, with diverse customer details, product variants, ticket wording/intents, dates, statuses, sellers, locations, and varied child records.
- [x] Remove `synthetic` from data filenames and CSV field values; update README record counts and fictional-data explanation.
- [x] Regenerate files and inspect counts, category/intent distributions, ID regexes, foreign keys, date validity, and evaluation references.

### Task 2: Capture official policy sources as PDFs

**Files:**
- Create: `output/pdf/policy_sources/` source PDFs and `manifest.csv`
- Preserve: `output/pdf/platform_policy_reference.pdf`
- Modify: `data/policy_sources.csv` only to add capture metadata/status fields if needed; do not alter policy content.

**Interfaces:**
- Manifest maps every source ID and unique source URL to a local PDF path, capture method/date, and result.
- Amazon.com remains flagged excluded and its PDF sits in the excluded reference directory.

- [x] Retrieve each unique URL from `data/policy_sources.csv`; save a source-provided PDF when available, otherwise print the official page to PDF.
- [x] Save the excluded Amazon.com source under a separate excluded subdirectory.
- [x] Create/update the capture manifest with all source IDs, URL, output path, capture timestamp/method, and status.
- [x] Reopen/extract text from each captured PDF to check readability and report blocked or unavailable URLs without third-party substitution.

### Task 3: Refresh documentation and verify deliverables

**Files:**
- Modify: `data/README.md`
- Modify if needed: `../specs/2026-10-30-data-scale-and-policy-capture-design.md`

- [x] Document generation command, table counts, ID pattern, fictional-data status, policy PDF directory, manifest, and excluded source handling.
- [x] Search CSV filenames and content for `synthetic` (case-insensitive); expect no matches.
- [x] Confirm policy evidence summaries remain unchanged and provide a concise capture/availability report.
