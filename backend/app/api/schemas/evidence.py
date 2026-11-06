"""Response schemas for SQL facts and policy evidence."""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Literal

from pydantic import Field

from .common import ReadStatus, SchemaModel, VersionedResponse


class OrderFact(SchemaModel):
    order_id: str
    status: str | None = None
    order_date: str | None = None
    estimated_delivery: str | None = None
    actual_delivery: str | None = None
    seller_type: str | None = None
    marketplace: str | None = None


class OrderItemFact(SchemaModel):
    item_id: str
    product_id: str | None = None
    product_name: str | None = None
    category: str | None = None
    quantity: Decimal | None = None
    unit_price_inr: Decimal | None = None
    condition_reported: str | None = None


class DeliveryEventFact(SchemaModel):
    event_id: str
    event_type: str | None = None
    event_time: str | None = None
    location: str | None = None
    source: str | None = None


class ReturnRefundFact(SchemaModel):
    return_id: str
    item_id: str | None = None
    requested_at: str | None = None
    status: str | None = None
    inspection_status: str | None = None
    refund_status: str | None = None
    source: str | None = None


class PolicyEvidence(SchemaModel):
    rank: int = Field(ge=1)
    score: float = Field(allow_inf_nan=False)
    document_id: str
    policy_id: str
    policy_version: str
    artifact_type: str
    status: str
    marketplace: str
    environment_scope: str
    section_id: str
    section_title: str
    chunk_id: str
    source_uri: str
    source_path: str
    source_file_sha256: str
    excerpt: str = Field(max_length=4096)
    jurisdiction: str = ""
    locale: str = ""
    effective_from: str = ""
    effective_to: str = ""
    synthetic_demo: bool = True
    intents: list[str] = Field(default_factory=list)
    categories: list[str] = Field(default_factory=list)


class LoyaltyAccountFact(SchemaModel):
    account_id: str = Field(min_length=1, max_length=128)
    loyalty_tier: str = Field(min_length=1, max_length=64)
    points_balance: int = Field(ge=0)
    account_status: str = Field(min_length=1, max_length=64)
    as_of: str
    source: str = Field(min_length=1, max_length=128)


class LoyaltyTransactionFact(SchemaModel):
    event_id: str = Field(min_length=1, max_length=128)
    order_id: str | None = Field(default=None, max_length=128)
    event_type: str = Field(min_length=1, max_length=64)
    points_delta: int
    status: str = Field(min_length=1, max_length=32)
    occurred_at: str
    expires_at: str | None = None
    reward_code: str | None = Field(default=None, max_length=128)
    source: str = Field(min_length=1, max_length=128)


class CustomerCommunicationFact(SchemaModel):
    communication_id: str = Field(min_length=1, max_length=128)
    order_id: str | None = Field(default=None, max_length=128)
    channel: str = Field(min_length=1, max_length=32)
    direction: str = Field(min_length=1, max_length=32)
    topic: str = Field(min_length=1, max_length=96)
    summary: str = Field(min_length=1, max_length=1000)
    occurred_at: str
    outcome: str = Field(min_length=1, max_length=64)
    source: str = Field(min_length=1, max_length=128)


class CustomerSupportContextResponse(VersionedResponse):
    source_systems: list[str]
    as_of: str
    status: ReadStatus
    order_id: str
    loyalty_account: LoyaltyAccountFact | None = None
    loyalty_transactions: list[LoyaltyTransactionFact] = Field(default_factory=list)
    prior_communications: list[CustomerCommunicationFact] = Field(default_factory=list)
    evidence_refs: dict[str, list[str]]
    missing_fields: list[str] = Field(default_factory=list)
    conflicts: list[str] = Field(default_factory=list)


class EvidenceItem(SchemaModel):
    evidence_id: str
    label: str
    value: Any = None
    source_system: str
    source_ref: str
    observed_at: str | None = None
    verification: Literal["source_record", "customer_report", "model_inference", "not_verified"]
    applicability: Literal["applicable", "not_applicable", "unknown"] = "unknown"
    explanation: str | None = None


class MissingInformation(SchemaModel):
    field: str
    reason: str
    source_system: str | None = None


class EvidenceConflict(SchemaModel):
    conflict_id: str
    description: str
    evidence_refs: list[str] = Field(min_length=1)
    resolution: Literal["human_review_required", "unresolved"] = "human_review_required"


class EvidenceLedger(SchemaModel):
    status: Literal["complete", "incomplete", "conflict"]
    source_facts: list[EvidenceItem] = Field(default_factory=list)
    policy_statements: list[EvidenceItem] = Field(default_factory=list)
    customer_reports: list[EvidenceItem] = Field(default_factory=list)
    assumptions: list[EvidenceItem] = Field(default_factory=list)
    missing_information: list[MissingInformation] = Field(default_factory=list)
    conflicts: list[EvidenceConflict] = Field(default_factory=list)
    as_of: str


class OrderSummaryResponse(VersionedResponse):
    source_system: str
    as_of: str
    status: ReadStatus
    order_id: str
    order: OrderFact | None
    items: list[OrderItemFact]
    evidence_refs: dict[str, list[str]]
    missing_fields: list[str] = Field(default_factory=list)


class OrderInvestigationEvidence(VersionedResponse):
    source_system: str
    as_of: str
    status: ReadStatus
    order_id: str
    order: OrderFact | None
    items: list[OrderItemFact]
    delivery_events: list[DeliveryEventFact]
    returns_refunds: list[ReturnRefundFact]
    evidence_refs: dict[str, list[str]]
    missing_fields: list[str] = Field(default_factory=list)
    eligibility_decided: Literal[False]


class DeliveryEventsResponse(VersionedResponse):
    source_system: str
    as_of: str
    status: ReadStatus
    order_id: str
    events: list[DeliveryEventFact]
    evidence_refs: list[str]
    missing_fields: list[str] = Field(default_factory=list)


class ReturnRefundResponse(VersionedResponse):
    source_system: str
    as_of: str
    status: ReadStatus
    order_id: str
    returns_refunds: list[ReturnRefundFact]
    evidence_refs: list[str]
    eligibility_decided: Literal[False]
    missing_fields: list[str] = Field(default_factory=list)


class PolicySearchResponse(VersionedResponse):
    status: Literal["found", "insufficient_data"] = "found"
    results: dict[str, list[PolicyEvidence]]
    collection: str | None
    corpus_scope: str
    missing_fields: list[str] = Field(default_factory=list)
