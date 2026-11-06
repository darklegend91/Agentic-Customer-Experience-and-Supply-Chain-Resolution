"""Read-only proposal inspection endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Path

from ...approval.permissions import WorkflowActor, authorize_order, authorize_ticket, get_workflow_actor
from ...approval.service import _proposal_payload, get_workflow_response
from ...approval.workflow_state import WorkflowNotFound, WorkflowStoreUnavailable, get_proposal
from ..schemas.workflow import WorkflowProposal, WorkflowResponse

router = APIRouter(prefix="/proposals", tags=["proposals"])


@router.get("/{proposal_id}", response_model=WorkflowProposal)
def read_proposal(
    proposal_id: str = Path(..., min_length=36, max_length=36),
    actor: WorkflowActor = Depends(get_workflow_actor),
) -> dict:
    try:
        row = get_proposal(proposal_id)
        if row.get("created_by") != actor.subject and "support_reviewer" not in actor.roles:
            raise HTTPException(status_code=403, detail="Caller is not authorized for this proposal")
        if row.get("ticket_id"):
            authorize_ticket(actor, str(row["ticket_id"]))
        if row.get("order_id"):
            authorize_order(actor, str(row["order_id"]))
        payload = _proposal_payload(row)
        assert payload is not None
        return payload
    except HTTPException:
        raise
    except WorkflowNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except WorkflowStoreUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/{proposal_id}/workflow", response_model=WorkflowResponse)
def read_proposal_workflow(
    proposal_id: str = Path(..., min_length=36, max_length=36),
    actor: WorkflowActor = Depends(get_workflow_actor),
) -> dict:
    try:
        row = get_proposal(proposal_id)
        if row.get("created_by") != actor.subject and "support_reviewer" not in actor.roles:
            raise HTTPException(status_code=403, detail="Caller is not authorized for this proposal")
        if row.get("ticket_id"):
            authorize_ticket(actor, str(row["ticket_id"]))
        if row.get("order_id"):
            authorize_order(actor, str(row["order_id"]))
        return get_workflow_response(str(row["workflow_id"]))
    except HTTPException:
        raise
    except WorkflowNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except WorkflowStoreUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
