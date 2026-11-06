"""Ticket intake, triage, and investigation contracts."""

from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from .common import (
    MethodsRequest,
    LocaleCode,
    OpaqueId,
    ReadStatus,
    SchemaModel,
    SearchQuery,
    TicketMessage,
    VersionedRequest,
    VersionedResponse,
)
from .evidence import (
    CustomerSupportContextResponse,
    EvidenceLedger,
    OrderInvestigationEvidence,
    PolicySearchResponse,
)


TicketIntent = Literal[
    "address_change", "compensation_request", "damaged_item", "delivery_delay",
    "delivery_dispute", "exchange_request", "general_policy", "incorrect_item",
    "invoice_request", "late_refund", "loyalty_points", "missing_accessory",
    "non_delivery", "order_cancellation", "order_status", "partial_delivery",
    "payment_question", "price_difference", "product_question", "refund_status",
    "return_eligibility", "return_pickup", "return_status", "reward_expiry",
    "reward_redemption", "other_or_unsupported",
]


class TicketEntities(SchemaModel):
    """Opaque identifiers extracted from the message as untrusted hints."""

    order_ids: list[OpaqueId] = Field(default_factory=list, max_length=10)
    item_ids: list[OpaqueId] = Field(default_factory=list, max_length=10)
    product_ids: list[OpaqueId] = Field(default_factory=list, max_length=10)
    return_ids: list[OpaqueId] = Field(default_factory=list, max_length=10)


class TicketClassifyRequest(VersionedRequest):
    message: TicketMessage


class TicketInvestigationRequest(MethodsRequest):
    ticket_id: OpaqueId | None = None
    message: TicketMessage | None = None
    order_id: OpaqueId | None = None
    query: SearchQuery | None = None
    locale: LocaleCode = "en-IN"
    top_k: int = Field(default=3, ge=1, le=10)

    @model_validator(mode="after")
    def require_ticket_or_message(self):
        if not self.ticket_id and not self.message:
            raise ValueError("provide a ticket_id, a message, or both")
        return self


class PolicySearchRequest(MethodsRequest):
    query: SearchQuery
    locale: LocaleCode = "en-IN"
    top_k: int = Field(default=3, ge=1, le=10)


class TicketRecord(VersionedResponse):
    status: ReadStatus = "found"
    ticket_id: str
    message: str | None
    order_id: str | None
    workflow_status: Literal["not_persisted"] = "not_persisted"
    missing_fields: list[str] = Field(default_factory=list)


class TicketDetailsResponse(TicketRecord):
    pass


class TicketClassification(VersionedResponse):
    intent: TicketIntent
    confidence: float = Field(ge=0, le=1, allow_inf_nan=False)
    classifier_version: str = Field(min_length=1, max_length=128)
    classifier_provider: Literal["laya", "tfidf_fallback", "input_guardrail", "deterministic_rule"] = "laya"
    fallback_used: bool = False
    triage_status: Literal["ready", "needs_review", "security_review"]
    risk_flags: list[str] = Field(default_factory=list, max_length=20)
    entities: TicketEntities = Field(default_factory=TicketEntities)
    review_threshold: float = Field(ge=0, le=1)
    needs_human_review: bool = True
    baseline_intent: TicketIntent | None = None
    models_agree: bool | None = None
    confidence_calibrated: Literal[False] = False
    automatic_routing_enabled: bool = False


class TicketClassificationResponse(VersionedResponse):
    request_id: str
    classification: TicketClassification


class TicketInvestigationResponse(VersionedResponse):
    request_id: str
    evidence_status: Literal["found", "insufficient_data"]
    ticket: TicketDetailsResponse | None
    classification: TicketClassification
    order_evidence: OrderInvestigationEvidence | None
    customer_context: CustomerSupportContextResponse | None = None
    policy_evidence: PolicySearchResponse
    evidence_ledger: EvidenceLedger | None = None
    missing_information: list[str] = Field(default_factory=list)
    limitations: list[str]
