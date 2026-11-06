# Policy Knowledge Base

## Source of truth

Store reviewed source files and versioned policy documents here. Preserve original source files and hashes. A captured web page, evidence summary, or model-generated text is not an approved policy.

## Layout

- policies/<policy-id>/<version>.md: policy terms and structured rules.
- faqs/<faq-id>/<version>.md: reviewed customer-facing answers linked to policy IDs.
- escalation_rules/<rule-id>/<version>.yaml: deterministic escalation conditions and destinations.

Every published artifact records its owner, reviewer, marketplace, jurisdiction, locale, category/intent scope, source URI, capture/verification time, effective dates, lifecycle status, and content hash. See docs/policy_schema.md.

Draft and in-review documents must not be indexed for production retrieval. Synthetic drafts may be indexed only into the isolated development collection `agentic_customer_support_dev_policies_v1`. The existing unversioned collection is not used by this Day 3 pipeline. Milvus is a rebuildable search index; files in this directory remain authoritative.

## Publication workflow

1. Capture the official source and store its provenance and hash.
2. Draft a policy record and mark it synthetic_demo when fictional.
3. Have the named policy owner review the terms and structured conditions.
4. Record the approver and effective dates, then publish a new immutable version.
5. Build and validate the index from approved versions only.
6. Retain superseded versions for audit; exclude them from current retrieval.

The captured PDFs are stored under output/pdf/ inside the canonical project, but they have not completed the versioned policy publication workflow in knowledge_base/.
