"""Authenticated human review API; approval resumes only a simulation path."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Header, HTTPException, Path, Request

from ...approval.permissions import WorkflowActor, authorize_order, authorize_ticket, require_reviewer
from ...approval.service import decide_proposal
from ...approval.workflow_state import (
    WorkflowConflict,
    WorkflowNotFound,
    WorkflowStoreUnavailable,
    get_proposal,
)
from ...observability.logging import log_safe_error
from ..schemas.approval import ApprovalDecisionRequest, ApprovalDecisionResponse

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/approvals", tags=["approvals"])


@router.post("/proposals/{proposal_id}/decision", response_model=ApprovalDecisionResponse)
def decide(
    proposal_id: str,
    request: ApprovalDecisionRequest,
    http_request: Request,
    idempotency_key: str = Header(..., alias="Idempotency-Key", min_length=1, max_length=128),
    actor: WorkflowActor = Depends(require_reviewer),
) -> dict:
    try:
        proposal = get_proposal(proposal_id)
        if proposal.get("ticket_id"):
            authorize_ticket(actor, str(proposal["ticket_id"]))
        if proposal.get("order_id"):
            authorize_order(actor, str(proposal["order_id"]))
        result = decide_proposal(
            proposal_id=proposal_id,
            actor=actor,
            decision=request.decision,
            expected_version=request.expected_proposal_version,
            idempotency_key=idempotency_key,
            comment=request.comment,
        )
        return result
    except HTTPException:
        raise
    except WorkflowNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (WorkflowConflict, ValueError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except WorkflowStoreUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        log_safe_error(
            logger,
            event="approval_decision_failed",
            request_id=http_request.state.request_id,
            stage="approval",
            error_type=type(exc).__name__,
        )
        raise HTTPException(status_code=503, detail="Approval service unavailable") from exc
