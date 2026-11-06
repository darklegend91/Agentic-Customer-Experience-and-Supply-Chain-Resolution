"""Human decision contracts. Approval never authorizes an external action."""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from .common import SchemaModel, VersionedResponse


class ApprovalDecisionRequest(SchemaModel):
    schema_version: Literal["1.0"]
    decision: Literal["approve", "reject"]
    expected_proposal_version: int = Field(ge=1)
    comment: str | None = Field(default=None, max_length=500)


class ApprovalDecisionResponse(VersionedResponse):
    proposal_id: str
    workflow_id: str
    decision: Literal["approve", "reject"]
    status: Literal["approved_simulation", "rejected", "invalidated", "pending_approval"]
    action_execution_status: Literal["not_available"] = "not_available"
    workflow: dict
