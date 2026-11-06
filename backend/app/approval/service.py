"""Workflow start, inspection, freshness-checked approval, and replay service."""

from __future__ import annotations

import logging
import uuid
from typing import Any

from langgraph.types import Command

from ..agents.graph import get_workflow_graph
from ..agents.investigation import gather_specialist_evidence
from ..api.schemas.workflow import WorkflowResponse
from ..observability.logging import log_safe_error
from ..security.pii_masking import mask_sensitive_text
from .permissions import WorkflowActor
from .workflow_state import (
    WorkflowConflict,
    WorkflowNotFound,
    WorkflowStoreUnavailable,
    complete_approval_decision,
    create_workflow_run,
    evidence_fingerprint,
    get_proposal,
    get_workflow,
    list_workflow_events,
    record_approval_decision,
    update_workflow,
)

logger = logging.getLogger(__name__)


def _graph_config(thread_id: str) -> dict[str, Any]:
    return {"configurable": {"thread_id": thread_id}}


def _summary_response(
    *,
    workflow_id: str,
    thread_id: str,
    status: str,
    summary: dict[str, Any] | None,
    proposal: dict[str, Any] | None = None,
) -> dict[str, Any]:
    summary = summary or {}
    payload = {
        "workflow_id": workflow_id,
        "thread_id": thread_id,
        "status": status,
        "classification": summary.get("classification"),
        "specialist": summary.get("specialist"),
        "answer": summary.get("answer"),
        "disposition": summary.get("disposition"),
        "evidence_refs": summary.get("evidence_refs", []),
        "missing_information": summary.get("missing_information", []),
        "reason_codes": summary.get("reason_codes", []),
        "proposal": proposal,
        "error_code": summary.get("error_code"),
    }
    return WorkflowResponse.model_validate(payload).model_dump(mode="json")


def _proposal_payload(row: dict[str, Any] | None) -> dict[str, Any] | None:
    if not row:
        return None
    payload = row.get("payload_json")
    payload = payload if isinstance(payload, dict) else {}
    return {
        "schema_version": "1.0",
        "proposal_id": str(row["proposal_id"]),
        "proposal_version": int(row["proposal_version"]),
        "status": str(row["status"]),
        "action_kind": str(row["action_kind"]),
        "action_execution_status": "not_available",
        "summary": str(row["summary"]),
        "permitted_options": row.get("permitted_options") or [],
        "evidence_refs": row.get("evidence_refs") or [],
        "policy_versions": row.get("policy_versions") or [],
        "evidence_fingerprint": str(row["evidence_fingerprint"]),
        "created_at": row.get("created_at"),
    }


def _require_simulation_only_proposal(proposal: dict[str, Any]) -> None:
    """Reject any proposal that could be mistaken for an executable action."""
    action_kind = str(proposal.get("action_kind") or "")
    permitted = set(proposal.get("permitted_options") or [])
    if not action_kind.endswith("_simulation") or permitted != {"approve_simulation", "reject"}:
        raise WorkflowConflict("Only simulation proposals are supported; no action executor is available")


def _workflow_status(row: dict[str, Any]) -> str:
    status = row.get("status")
    return str(status) if status in {
        "running", "needs_information", "escalated", "answer_ready", "pending_approval",
        "approved_simulation", "rejected", "invalidated", "failed_safe",
    } else "failed_safe"


def queue_workflow(
    *,
    request_id: str,
    actor: WorkflowActor,
    ticket_id: str | None,
    message: str | None,
    order_id: str | None,
    query: str | None,
    top_k: int,
    methods: list[str],
    locale: str = "en-IN",
    persist_job: bool = True,
) -> tuple[dict[str, Any], dict[str, Any]]:
    workflow_id = str(uuid.uuid4())
    # Use a separate graph thread identifier so API/database IDs remain opaque.
    thread_id = str(uuid.uuid4())
    state = {
        "workflow_id": workflow_id,
        "thread_id": thread_id,
        "request_id": request_id,
        "created_by": actor.subject,
        "ticket_id": ticket_id,
        # Mask before the initial LangGraph checkpoint so raw contact/payment values
        # never enter durable graph state.
        "message": mask_sensitive_text(message or ""),
        "order_id": order_id,
        "query": mask_sensitive_text(query) if query else None,
        "locale": locale,
        "top_k": top_k,
        "methods": methods,
        "allowed_ticket_ids": sorted(actor.allowed_ticket_ids),
        "allowed_order_ids": sorted(actor.allowed_order_ids),
        "status": "running",
    }
    create_workflow_run(
        workflow_id=workflow_id,
        thread_id=thread_id,
        request_id=request_id,
        created_by=actor.subject,
        ticket_id=ticket_id,
        order_id=order_id,
        job_payload=state if persist_job else None,
    )
    response = _summary_response(
        workflow_id=workflow_id,
        thread_id=thread_id,
        status="running",
        summary={"status": "running", "request_id": request_id},
    )
    return response, state


def execute_workflow(state: dict[str, Any]) -> None:
    """Execute a persisted workflow payload; safe to retry from its LangGraph checkpoint."""
    workflow_id = str(state["workflow_id"])
    thread_id = str(state["thread_id"])
    request_id = str(state["request_id"])
    try:
        current = get_workflow(workflow_id)
        if current.get("status") != "running":
            return
        get_workflow_graph().invoke(state, _graph_config(thread_id))
    except Exception as exc:
        log_safe_error(
            logger,
            event="workflow_execution_failed",
            request_id=request_id,
            stage="workflow",
            error_type=type(exc).__name__,
        )
        update_workflow(
            workflow_id,
            status="failed_safe",
            summary={
                "status": "failed_safe",
                "request_id": request_id,
                "answer": "The workflow could not be completed safely. Please route this case to human support.",
                "error_code": "workflow_execution_failed",
                "reason_codes": ["workflow_execution_failed"],
                "evidence_refs": [],
                "missing_information": [],
            },
            error_code="workflow_execution_failed",
            stage="workflow",
            event_type="workflow_failed_safe",
            event_details={"error_type": type(exc).__name__},
        )


def start_workflow(
    *,
    request_id: str,
    actor: WorkflowActor,
    ticket_id: str | None,
    message: str | None,
    order_id: str | None,
    query: str | None,
    top_k: int,
    methods: list[str],
    locale: str = "en-IN",
) -> dict[str, Any]:
    """Synchronous service helper retained for direct callers and local scripts."""
    response, state = queue_workflow(
        request_id=request_id,
        actor=actor,
        ticket_id=ticket_id,
        message=message,
        order_id=order_id,
        query=query,
        locale=locale,
        top_k=top_k,
        methods=methods,
        persist_job=False,
    )
    execute_workflow(state)
    return get_workflow_response(response["workflow_id"])


def get_workflow_response(workflow_id: str) -> dict[str, Any]:
    row = get_workflow(workflow_id)
    proposal_row = get_proposal(str(row["proposal_id"])) if row.get("proposal_id") else None
    return _summary_response(
        workflow_id=str(row["workflow_id"]),
        thread_id=str(row["thread_id"]),
        status=_workflow_status(row),
        summary=row.get("summary_json"),
        proposal=_proposal_payload(proposal_row),
    )


_NODE_LABELS = {
    "prepare_input": "Validate and mask ticket input",
    "triage": "Classify intent with Laya",
    "supervisor": "Supervisor selects an allowlisted specialist",
    "policy_faq": "Policy and FAQ specialist retrieves evidence",
    "order_delivery": "Order and delivery specialist reads SQL evidence",
    "return_refund": "Return and refund specialist checks evidence",
    "product_issue": "Product issue specialist checks evidence",
    "manual_review": "Route to human review",
    "consolidate_evidence": "Consolidate and cite evidence",
    "deterministic_rules": "Apply deterministic policy and evidence rules",
    "draft_response": "Draft an evidence-grounded response",
    "validate_response": "Validate answer and citations",
    "persist_proposal": "Persist a versioned resolution proposal",
    "approval_interrupt": "Pause for human approval",
    "safe_fallback": "Select a safe fallback",
    "finalize": "Persist final workflow status",
}


def get_workflow_trace(workflow_id: str) -> dict[str, Any]:
    """Return the latest checkpoint's active node and safe, useful working outputs."""
    row = get_workflow(workflow_id)
    checkpoint = get_workflow_graph().get_state(_graph_config(str(row["thread_id"])))
    state = dict(checkpoint.values or {})
    next_nodes = list(checkpoint.next or ())
    current_node = next_nodes[0] if next_nodes else None
    status = _workflow_status(row)
    if status == "pending_approval":
        current_node = "approval_interrupt"
    elif status == "running" and current_node is None:
        current_node = "prepare_input"
    elif status != "running" and status not in {"pending_approval"}:
        current_node = None
    return {
        "workflow_id": workflow_id,
        "status": status,
        "current_node": current_node,
        "current_step": _NODE_LABELS.get(current_node) if current_node else None,
        "classification": state.get("classification"),
        "specialist": state.get("specialist"),
        "evidence": state.get("evidence") or {},
        "resolution": state.get("resolution") or {},
        "draft": state.get("draft") or {},
        "answer": state.get("answer"),
    }


def get_workflow_events(workflow_id: str, *, limit: int = 100) -> list[dict[str, Any]]:
    return list_workflow_events(workflow_id, limit=limit)


def _refresh_evidence(state: dict[str, Any]) -> dict[str, Any]:
    specialist = str(state.get("specialist") or "")
    return gather_specialist_evidence(state, specialist)


def decide_proposal(
    *,
    proposal_id: str,
    actor: WorkflowActor,
    decision: str,
    expected_version: int,
    idempotency_key: str,
    comment: str | None,
) -> dict[str, Any]:
    proposal = get_proposal(proposal_id)
    _require_simulation_only_proposal(proposal)
    workflow_id = str(proposal["workflow_id"])
    thread_id = str(proposal["thread_id"])
    if actor.subject == str(proposal["created_by"]):
        raise WorkflowConflict("A proposal creator may not approve or reject their own proposal")

    recorded = record_approval_decision(
        proposal_id=proposal_id,
        decision=decision,
        actor_id=actor.subject,
        expected_version=expected_version,
        idempotency_key=idempotency_key,
        comment=mask_sensitive_text(comment)[:500] if comment else None,
    )
    current_proposal = recorded["proposal"]
    if current_proposal.get("status") in {"approved_simulation", "rejected", "invalidated"}:
        return {
            "proposal_id": proposal_id,
            "workflow_id": workflow_id,
            "decision": decision,
            "status": current_proposal["status"],
            "action_execution_status": "not_available",
            "workflow": get_workflow_response(workflow_id),
        }

    graph = get_workflow_graph()
    config = _graph_config(thread_id)
    checkpoint = graph.get_state(config)
    state = dict(checkpoint.values or {})
    state_proposal = state.get("proposal") or {}
    if (
        not checkpoint.values
        or state.get("status") != "pending_approval"
        or str(state_proposal.get("proposal_id")) != proposal_id
        or int(state_proposal.get("proposal_version", -1)) != expected_version
    ):
        raise WorkflowConflict("The proposal is not paused at the expected workflow checkpoint")

    evidence_valid = decision == "reject"
    if decision == "approve":
        try:
            refreshed = _refresh_evidence(state)
            fresh_evidence = refreshed.get("evidence") or {}
            evidence_valid = (
                not refreshed.get("specialist_error_code")
                and evidence_fingerprint(fresh_evidence) == str(proposal["evidence_fingerprint"])
            )
        except Exception as exc:
            log_safe_error(
                logger,
                event="approval_evidence_refresh_failed",
                request_id=str(state.get("request_id") or "unavailable"),
                stage="approval_revalidation",
                error_type=type(exc).__name__,
            )

    resume_decision = "approve" if decision == "approve" and evidence_valid else decision
    if decision == "approve" and not evidence_valid:
        resume_decision = "invalidate"
    resume = {
        "decision": resume_decision,
        "evidence_valid": evidence_valid,
        "actor_id": actor.subject,
        "expected_proposal_version": expected_version,
    }
    result = graph.invoke(Command(resume=resume), config)
    final_state = result if isinstance(result, dict) else {}
    workflow_status = str(final_state.get("status") or "failed_safe")
    if workflow_status not in {"approved_simulation", "rejected", "invalidated"}:
        workflow_status = "failed_safe"
    proposal_status = {
        "approved_simulation": "approved_simulation",
        "rejected": "rejected",
        "invalidated": "invalidated",
        "failed_safe": "invalidated",
    }[workflow_status]
    complete_approval_decision(
        proposal_id=proposal_id,
        workflow_id=workflow_id,
        idempotency_key=idempotency_key,
        proposal_status=proposal_status,
        workflow_status=workflow_status,
        summary={
            "status": workflow_status,
            "request_id": final_state.get("request_id"),
            "classification": final_state.get("classification"),
            "specialist": final_state.get("specialist"),
            "answer": final_state.get("answer"),
            "disposition": workflow_status,
            "evidence_refs": final_state.get("evidence_refs", []),
            "missing_information": [],
            "reason_codes": ["approval_evidence_stale"] if not evidence_valid else [],
        },
        event_type={
            "approved_simulation": "proposal_approved_simulation",
            "rejected": "proposal_rejected",
            "invalidated": "proposal_invalidated_stale_evidence",
            "failed_safe": "approval_resume_failed_safe",
        }[workflow_status],
        actor_id=actor.subject,
    )
    final_proposal = get_proposal(proposal_id)
    return {
        "proposal_id": proposal_id,
        "workflow_id": workflow_id,
        "decision": decision,
        "status": final_proposal["status"],
        "action_execution_status": "not_available",
        "workflow": get_workflow_response(workflow_id),
    }
