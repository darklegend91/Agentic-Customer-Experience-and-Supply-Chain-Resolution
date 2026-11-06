"""Request and response contracts for controlled LangGraph investigations."""

from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from .common import LocaleCode, MethodsRequest, OpaqueId, SearchQuery, TicketMessage, VersionedResponse
from .ticket import TicketClassification


WorkflowStatus = Literal[
    "running",
    "needs_information",
    "escalated",
    "answer_ready",
    "pending_approval",
    "approved_simulation",
    "rejected",
    "invalidated",
    "failed_safe",
]


class WorkflowStartRequest(MethodsRequest):
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


class WorkflowProposal(VersionedResponse):
    proposal_id: str
    proposal_version: int = Field(ge=1)
    status: Literal[
        "pending_approval",
        "decision_recorded",
        "approved_simulation",
        "rejected",
        "invalidated",
    ]
    action_kind: str
    action_execution_status: Literal["not_available"] = "not_available"
    summary: str
    permitted_options: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    policy_versions: list[str] = Field(default_factory=list)
    evidence_fingerprint: str
    created_at: str | None = None


class WorkflowResponse(VersionedResponse):
    workflow_id: str
    thread_id: str
    status: WorkflowStatus
    classification: TicketClassification | None = None
    specialist: str | None = None
    answer: str | None = None
    disposition: str | None = None
    evidence_refs: list[str] = Field(default_factory=list)
    missing_information: list[str] = Field(default_factory=list)
    reason_codes: list[str] = Field(default_factory=list)
    proposal: WorkflowProposal | None = None
    error_code: str | None = None


class WorkflowTraceResponse(VersionedResponse):
    workflow_id: str
    status: WorkflowStatus
    current_node: str | None = None
    current_step: str | None = None
    classification: TicketClassification | None = None
    specialist: str | None = None
    evidence: dict = Field(default_factory=dict)
    resolution: dict = Field(default_factory=dict)
    draft: dict = Field(default_factory=dict)
    answer: str | None = None


class WorkflowEvent(VersionedResponse):
    event_id: str
    workflow_id: str
    stage: str
    event_type: str
    actor_id: str | None = None
    occurred_at: str
    details: dict = Field(default_factory=dict)
