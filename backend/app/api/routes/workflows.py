"""Protected LangGraph workflow start and status endpoints."""

from __future__ import annotations

import logging

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Path, Query, Request

from ...approval.permissions import WorkflowActor, authorize_order, authorize_ticket, get_workflow_actor, require_support
from ...approval.service import (
    execute_workflow,
    get_workflow_events,
    get_workflow_response,
    get_workflow_trace,
    queue_workflow,
)
from ...approval.workflow_state import (
    WorkflowConflict,
    WorkflowNotFound,
    WorkflowStoreUnavailable,
    get_workflow,
)
from ...observability.logging import log_safe_error
from ..schemas.workflow import WorkflowEvent, WorkflowResponse, WorkflowStartRequest, WorkflowTraceResponse, WorkflowSnapshotResponse

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/workflows", tags=["workflows"])


@router.get("/{workflow_id}/snapshot", response_model=WorkflowSnapshotResponse)
def read_workflow_snapshot(
    workflow_id: str = Path(..., min_length=36, max_length=36),
    actor: WorkflowActor = Depends(get_workflow_actor),
) -> dict:
    """Authorize once, reuse the row, and fetch one UI refresh in one request."""
    try:
        row = get_workflow(workflow_id)
        if row.get("created_by") != actor.subject and "support_reviewer" not in actor.roles:
            raise HTTPException(status_code=403, detail="Caller is not authorized for this workflow")
        if row.get("ticket_id"):
            authorize_ticket(actor, str(row["ticket_id"]))
        if row.get("order_id"):
            authorize_order(actor, str(row["order_id"]))
        workflow = get_workflow_response(workflow_id, row=row)
        events = get_workflow_events(workflow_id)
        if workflow["status"] == "running":
            # Audit events already carry live stage progress. Loading the full
            # Postgres checkpoint on every poll adds several cross-region reads.
            last_stage = str(events[-1]["stage"]) if events else "intake"
            trace = {
                "workflow_id": workflow_id, "status": "running",
                "current_node": last_stage,
                "current_step": "Processing stage: " + last_stage.replace("_", " "),
                "classification": workflow.get("classification"),
                "specialist": workflow.get("specialist"),
                "evidence": {}, "resolution": {}, "draft": {}, "answer": None,
            }
        else:
            trace = get_workflow_trace(workflow_id, row=row)
        return {
            "workflow": workflow,
            "trace": trace,
            "events": [{
                "event_id": str(event["event_id"]),
                "workflow_id": str(event["workflow_id"]),
                "stage": event["stage"],
                "event_type": event["event_type"],
                "actor_id": event.get("actor_id"),
                "occurred_at": event["occurred_at"],
                "details": event.get("details_json") or {},
            } for event in events],
        }
    except WorkflowNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except WorkflowStoreUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("", response_model=WorkflowResponse, status_code=202)
def create_workflow(
    request: WorkflowStartRequest,
    http_request: Request,
    background_tasks: BackgroundTasks,
    actor: WorkflowActor = Depends(require_support),
) -> dict:
    if request.ticket_id:
        authorize_ticket(actor, request.ticket_id)
    if request.order_id:
        authorize_order(actor, request.order_id)
    try:
        response, state = queue_workflow(
            request_id=http_request.state.request_id,
            actor=actor,
            ticket_id=request.ticket_id,
            message=request.message,
            order_id=request.order_id,
            query=request.query,
            locale=request.locale,
            top_k=request.top_k,
            methods=[str(method) for method in request.methods],
        )
        # Execute immediately in background task to eliminate worker poll latency
        background_tasks.add_task(execute_workflow, state)
        return response
    except HTTPException:
        raise
    except (WorkflowConflict, ValueError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except WorkflowStoreUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        log_safe_error(
            logger,
            event="workflow_start_failed",
            request_id=http_request.state.request_id,
            stage="workflow_start",
            error_type=type(exc).__name__,
        )
        raise HTTPException(status_code=503, detail="Workflow service unavailable") from exc


@router.get("/{workflow_id}", response_model=WorkflowResponse)
def read_workflow(
    workflow_id: str = Path(..., min_length=36, max_length=36),
    actor: WorkflowActor = Depends(get_workflow_actor),
) -> dict:
    try:
        row = get_workflow(workflow_id)
        if row.get("created_by") != actor.subject and "support_reviewer" not in actor.roles:
            raise HTTPException(status_code=403, detail="Caller is not authorized for this workflow")
        if row.get("ticket_id"):
            authorize_ticket(actor, str(row["ticket_id"]))
        if row.get("order_id"):
            authorize_order(actor, str(row["order_id"]))
        return get_workflow_response(workflow_id)
    except HTTPException:
        raise
    except WorkflowNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except WorkflowStoreUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/{workflow_id}/trace", response_model=WorkflowTraceResponse)
def read_workflow_trace(
    workflow_id: str = Path(..., min_length=36, max_length=36),
    actor: WorkflowActor = Depends(get_workflow_actor),
) -> dict:
    try:
        row = get_workflow(workflow_id)
        if row.get("created_by") != actor.subject and "support_reviewer" not in actor.roles:
            raise HTTPException(status_code=403, detail="Caller is not authorized for this workflow")
        if row.get("ticket_id"):
            authorize_ticket(actor, str(row["ticket_id"]))
        if row.get("order_id"):
            authorize_order(actor, str(row["order_id"]))
        return get_workflow_trace(workflow_id)
    except HTTPException:
        raise
    except WorkflowNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except WorkflowStoreUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/{workflow_id}/events", response_model=list[WorkflowEvent])
def read_workflow_events(
    workflow_id: str = Path(..., min_length=36, max_length=36),
    limit: int = Query(default=100, ge=1, le=200),
    actor: WorkflowActor = Depends(get_workflow_actor),
) -> list[dict]:
    try:
        row = get_workflow(workflow_id)
        if row.get("created_by") != actor.subject and "support_reviewer" not in actor.roles:
            raise HTTPException(status_code=403, detail="Caller is not authorized for this workflow")
        if row.get("ticket_id"):
            authorize_ticket(actor, str(row["ticket_id"]))
        if row.get("order_id"):
            authorize_order(actor, str(row["order_id"]))
        events = get_workflow_events(workflow_id, limit=limit)
        return [
            {
                "event_id": str(event.get("event_id")),
                "workflow_id": str(event.get("workflow_id")),
                "stage": event.get("stage"),
                "event_type": event.get("event_type"),
                "actor_id": event.get("actor_id"),
                "occurred_at": event.get("occurred_at"),
                "details": event.get("details_json") or {},
            }
            for event in events
        ]
    except HTTPException:
        raise
    except WorkflowNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except WorkflowStoreUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
