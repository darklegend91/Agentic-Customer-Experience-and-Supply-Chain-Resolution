"""LangGraph controlled investigation workflow and durable checkpoint lifecycle."""

from __future__ import annotations

import logging
import os
import threading
import uuid
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
from typing import Any
from collections.abc import Mapping
from typing_extensions import TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from ..approval.workflow_state import (
    WorkflowStoreUnavailable,
    evidence_fingerprint,
    record_stage_event,
    record_stage_events,
    save_proposal,
    update_workflow,
    update_workflow_order_scope,
)
from ..domain.resolution_rules import evaluate_resolution
from ..guardrails.evidence_validation import (
    build_evidence_ledger,
    validate_evidence_ledger,
)
from ..guardrails.output_validation import validate_draft
from ..observability.logging import log_safe_error
from ..observability.tracing import trace_stage, traced_stage
from .investigation import (
    loyalty_rewards_specialist,
    order_delivery_specialist,
    policy_faq_specialist,
    prepare_input,
    product_issue_specialist,
    return_refund_specialist,
)
from .response_generation import (
    canonical_answer,
    draft_grounded_response,
    recorded_claims,
)
from .supervisor import supervisor_route
from .triage import triage_ticket

logger = logging.getLogger(__name__)


class WorkflowState(TypedDict, total=False):
    workflow_id: str
    thread_id: str
    request_id: str
    created_by: str
    ticket_id: str | None
    message: str
    order_id: str | None
    query: str | None
    methods: list[str]
    top_k: int
    locale: str
    allowed_ticket_ids: list[str]
    allowed_order_ids: list[str]
    input_error_code: str | None
    classification: dict[str, Any] | None
    triage_ready: bool
    triage_reason_codes: list[str]
    specialist: str
    specialist_error_code: str | None
    specialist_error_type: str | None
    evidence: dict[str, Any]
    evidence_refs: list[str]
    resolution: dict[str, Any]
    draft: dict[str, Any]
    draft_provider: str
    draft_error_code: str | None
    validation_errors: list[str]
    proposal: dict[str, Any]
    approval_decision: dict[str, Any]
    answer: str | None
    status: str
    disposition: str | None
    missing_information: list[str]
    reason_codes: list[str]
    error_code: str | None


_GRAPH_LOCK = threading.RLock()
_GRAPH: Any = None
_CHECKPOINT_POOL: Any = None
_CHECKPOINT_DSN: str | None = None


def _safe_summary(state: dict[str, Any]) -> dict[str, Any]:
    classification = state.get("classification") or {}
    proposal = state.get("proposal") or {}
    resolution = state.get("resolution") or {}
    return {
        "status": state.get("status", "failed_safe"),
        "request_id": state.get("request_id"),
        "classification": classification,
        "specialist": state.get("specialist"),
        "answer": state.get("answer"),
        "disposition": state.get("disposition"),
        "evidence_refs": state.get("evidence_refs", []),
        "missing_information": state.get("missing_information", []),
        "reason_codes": state.get("reason_codes", []),
        "proposal_id": proposal.get("proposal_id"),
        "proposal_version": proposal.get("proposal_version"),
        "error_code": state.get("error_code"),
        "resolution_outcome": resolution.get("outcome"),
    }


def _response_refs(state: dict[str, Any]) -> set[str]:
    refs: set[str] = set()
    for value in state.get("evidence_refs") or []:
        refs.add(str(value))
    evidence = state.get("evidence") or {}
    order = evidence.get("order") or {}
    for values in (order.get("evidence_refs") or {}).values():
        for value in values if isinstance(values, list) else []:
            refs.add(str(value))
    return refs


def build_workflow_graph(*, checkpointer: Any = None, persistence_enabled: bool = True):
    """Build the graph; pass an in-memory checkpointer in tests only."""

    pending_events: ContextVar[list[dict[str, Any]] | None] = ContextVar("workflow_audit_batch", default=None)

    @contextmanager
    def audit_batch(workflow_id: str):
        entries: list[dict[str, Any]] = []
        token = pending_events.set(entries)
        try:
            yield
        finally:
            pending_events.reset(token)
            if persistence_enabled:
                record_stage_events(workflow_id, entries)

    def event(state: Mapping[str, Any], stage: str, event_type: str, details: dict[str, Any] | None = None) -> None:
        if persistence_enabled:
            batch = pending_events.get()
            if batch is not None:
                batch.append({"stage": stage, "event_type": event_type, "details": details,
                              "occurred_at": datetime.now(timezone.utc)})
                return
            record_stage_event(
                str(state["workflow_id"]),
                stage=stage,
                event_type=event_type,
                details=details,
            )

    def input_node(state: Mapping[str, Any]) -> dict[str, Any]:
        result = prepare_input(dict(state))
        if result.get("input_error_code"):
            status = result.get("status", "failed_safe")
            event(state, "input", "input_rejected", {"reason_code": result["input_error_code"]})
            return {**result, "status": status, "error_code": result["input_error_code"]}
        if persistence_enabled and result.get("order_id"):
            update_workflow_order_scope(str(state["workflow_id"]), order_id=str(result["order_id"]))
        event(state, "input", "input_validated", {"order_reference_present": bool(result.get("order_id"))})
        return result

    def triage_node(state: Mapping[str, Any]) -> dict[str, Any]:
        try:
            result = triage_ticket(dict(state))
        except Exception as exc:
            log_safe_error(
                logger,
                event="workflow_triage_failed",
                request_id=str(state.get("request_id") or "unavailable"),
                stage="triage",
                error_type=type(exc).__name__,
            )
            event(state, "triage", "triage_failed", {"error_type": type(exc).__name__})
            return {
                "status": "failed_safe",
                "error_code": "classification_unavailable",
                "triage_ready": False,
                "reason_codes": ["classification_unavailable"],
            }
        classification = result.get("classification") or {}
        event(state, "triage", "ticket_classified", {
            "intent": classification.get("intent"),
            "confidence": classification.get("confidence"),
            "classifier_provider": classification.get("classifier_provider"),
            "triage_ready": result.get("triage_ready", False),
        })
        return result

    def supervisor_node(state: Mapping[str, Any]) -> dict[str, Any]:
        result = supervisor_route(dict(state))
        event(state, "supervisor", "specialist_selected", {"specialist": result["specialist"]})
        return result

    def specialist_node(state: Mapping[str, Any], name: str, handler) -> dict[str, Any]:
        result = handler(dict(state))
        evidence = result.get("evidence") or {}
        order = evidence.get("order") or {}
        policy = evidence.get("policy") or {}
        customer_context = evidence.get("customer_context") or {}
        event(state, name, "specialist_evidence_collected" if not result.get("specialist_error_code") else "specialist_failed", {
            "order_status": order.get("status"),
            "policy_status": policy.get("status"),
            "customer_context_status": customer_context.get("status"),
            "evidence_reference_count": len(result.get("evidence_refs") or []),
            "error_type": result.get("specialist_error_type"),
        })
        return result

    def consolidate_node(state: Mapping[str, Any]) -> dict[str, Any]:
        if state.get("specialist_error_code"):
            return {
                "status": "failed_safe",
                "error_code": state["specialist_error_code"],
                "reason_codes": ["evidence_dependency_unavailable"],
            }
        refs = _response_refs(dict(state))
        evidence = dict(state.get("evidence") or {})
        ledger = build_evidence_ledger(
            message=str(state.get("message") or ""),
            ticket_id=state.get("ticket_id"),
            classification=state.get("classification") or {},
            evidence=evidence,
            missing_information=list(state.get("missing_information") or []),
            locale=str(state.get("locale") or "en-IN"),
        )
        event(state, "evidence", "evidence_consolidated", {"reference_count": len(refs)})
        return {
            "evidence": {**evidence, "ledger": ledger},
            "evidence_refs": sorted(refs),
            "status": "running",
        }

    def resolution_node(state: Mapping[str, Any]) -> dict[str, Any]:
        with trace_stage("rules.deterministic_checks"):
            resolution = evaluate_resolution(dict(state))
        event(state, "policy_rules", "deterministic_rules_evaluated", {
            "outcome": resolution.get("outcome"),
            "reason_codes": resolution.get("reason_codes", []),
            "requires_approval": resolution.get("requires_approval", False),
        })
        return {
            "resolution": resolution,
            "disposition": resolution.get("outcome"),
            "missing_information": resolution.get("missing_information", []),
            "reason_codes": resolution.get("reason_codes", []),
        }

    def draft_node(state: Mapping[str, Any]) -> dict[str, Any]:
        try:
            with trace_stage("response.draft"):
                result = draft_grounded_response(dict(state))
        except Exception as exc:
            log_safe_error(
                logger,
                event="workflow_response_draft_failed",
                request_id=str(state.get("request_id") or "unavailable"),
                stage="response_generation",
                error_type=type(exc).__name__,
            )
            event(state, "response", "response_draft_failed", {"error_type": type(exc).__name__})
            return {"draft_error_code": "response_drafting_failed", "draft": {}}
        event(state, "response", "response_drafted", {"provider": result.get("draft_provider")})
        return result

    @traced_stage("response.validation")
    def validate_node(state: Mapping[str, Any]) -> dict[str, Any]:
        if state.get("draft_error_code"):
            errors = ["response_drafting_failed"]
        else:
            provider = state.get("draft_provider")
            expected_answer = (
                canonical_answer(dict(state), recorded_claims(dict(state)))
                if provider == "deterministic_template"
                else None
            )
            expected_claims = (
                recorded_claims(dict(state))
                if provider in {"deterministic_template", "deterministic_fallback", "groq"}
                else None
            )
            errors = validate_draft(
                dict(state.get("draft") or {}),
                _response_refs(dict(state)),
                answer_required=True,
                expected_claims=expected_claims,
                expected_answer=expected_answer,
            )
            errors.extend(validate_evidence_ledger(((state.get("evidence") or {}).get("ledger") or {})))
        event(state, "output_validation", "output_validation_completed", {
            "valid": not errors,
            "error_codes": errors,
        })
        if errors:
            return {
                "validation_errors": errors,
                "status": "escalated",
                "error_code": "response_validation_failed",
                "reason_codes": ["response_validation_failed"],
            }
        return {
            "validation_errors": [],
            "answer": state.get("draft", {}).get("answer"),
            "status": "answer_ready",
            "disposition": "answer",
            "error_code": None,
        }

    def fallback_node(state: Mapping[str, Any]) -> dict[str, Any]:
        current = state.get("status")
        if current not in {"needs_information", "escalated", "failed_safe"}:
            codes = list(state.get("reason_codes") or []) + list(state.get("triage_reason_codes") or [])
            if state.get("missing_information") or "order_id" in codes:
                current = "needs_information"
            elif state.get("error_code") or state.get("specialist_error_code"):
                current = "failed_safe"
            else:
                current = "escalated"
        answer = None
        if current == "needs_information":
            answer = "I need the missing order or item details before I can investigate this request."
        elif current == "failed_safe":
            answer = "I could not complete the investigation safely because a required service failed. Please route this case to a human support agent."
        else:
            answer = "I could not verify an approved policy or sufficient evidence for this request. Please route it to a human support agent."
        codes = list(state.get("reason_codes") or [])
        if not codes:
            codes = list(state.get("triage_reason_codes") or [])
        if state.get("error_code") and state["error_code"] not in codes:
            codes.append(state["error_code"])
        if current == "escalated" and state.get("specialist") == "manual_review":
            if "model_safety_check_not_passed" in codes or "possible_instruction_override" in codes:
                answer = "The input safety check flagged this message or could not verify it safely. A support agent needs to review it before any investigation tools are used."
            elif "classifier_disagreement" in codes:
                answer = "The intent classifiers disagree, so I paused before investigating. A support agent needs to confirm the request type."
            elif "automatic_routing_disabled_by_policy" in codes:
                answer = "This request requires a support agent to confirm its type before investigation because automatic model routing is disabled."
        event(state, "fallback", "safe_fallback_selected", {"status": current, "reason_codes": codes})
        return {"status": current, "answer": answer, "reason_codes": sorted(set(codes))}

    def proposal_node(state: Mapping[str, Any]) -> dict[str, Any]:
        resolution = state.get("resolution") or {}
        candidate = resolution.get("proposal") or {}
        if (
            not str(candidate.get("action_kind") or "").endswith("_simulation")
            or set(candidate.get("permitted_options") or []) != {"approve_simulation", "reject"}
        ):
            raise ValueError("Only non-executing simulation proposals may enter human approval")
        proposal_id = str(uuid.uuid4())
        proposal: dict[str, Any] = {
            "schema_version": "1.0",
            "proposal_id": proposal_id,
            "proposal_version": 1,
            "status": "pending_approval",
            **candidate,
            "action_execution_status": "not_available",
            "evidence_fingerprint": evidence_fingerprint(state.get("evidence") or {}),
        }
        if persistence_enabled:
            save_proposal(
                proposal_id=proposal_id,
                workflow_id=str(state["workflow_id"]),
                action_kind=str(proposal["action_kind"]),
                summary=str(proposal["summary"]),
                permitted_options=list(proposal.get("permitted_options") or []),
                evidence_refs=list(proposal.get("evidence_refs") or []),
                policy_versions=list(proposal.get("policy_versions") or []),
                evidence_fingerprint=proposal["evidence_fingerprint"],
                proposal_payload=proposal,
                workflow_summary=_safe_summary({
                    **dict(state),
                    "proposal": proposal,
                    "status": "pending_approval",
                    "disposition": "proposal",
                }),
                classification=state.get("classification"),
            )
        event(state, "proposal", "proposal_persisted_for_approval", {
            "proposal_id": proposal_id,
            "proposal_version": 1,
            "action_kind": proposal["action_kind"],
        })
        return {"proposal": proposal, "status": "pending_approval", "disposition": "proposal"}

    def approval_node(state: Mapping[str, Any]) -> dict[str, Any]:
        proposal = state.get("proposal") or {}
        # interrupt() is the first side effect in this node; resume cannot repeat writes.
        decision = interrupt({
            "kind": "human_approval_required",
            "workflow_id": state.get("workflow_id"),
            "proposal": proposal,
        })
        if not isinstance(decision, dict):
            return {"status": "failed_safe", "error_code": "invalid_approval_resume"}
        choice = decision.get("decision")
        if choice == "approve" and decision.get("evidence_valid") is True:
            status = "approved_simulation"
            answer = "The reviewer approved this proposal for simulation. No external order, refund, replacement, or compensation action was executed."
        elif choice == "reject":
            status = "rejected"
            answer = "The reviewer rejected the proposal. No external action was executed."
        elif choice == "invalidate":
            status = "invalidated"
            answer = "The proposal evidence changed or could not be revalidated. Start a new investigation before requesting approval."
        else:
            status = "failed_safe"
            answer = "The approval response was invalid, so the workflow stopped safely."
        event(state, "approval", "approval_workflow_resumed", {
            "decision": choice if choice in {"approve", "reject", "invalidate"} else "invalid",
            "status": status,
        })
        return {"approval_decision": decision, "status": status, "answer": answer}

    def finalize_node(state: Mapping[str, Any]) -> dict[str, Any]:
        status = str(state.get("status") or "failed_safe")
        summary = _safe_summary(dict(state))
        if status == "answer_ready":
            # Persist the already validated presentation beside the summary so
            # the UI does not reopen the checkpoint merely to display an answer.
            summary["completed_trace"] = {
                "workflow_id": str(state["workflow_id"]), "status": status,
                "current_node": None, "current_step": None,
                **{key: state.get(key) for key in ("classification", "specialist", "answer")},
                **{key: state.get(key) or {} for key in ("evidence", "resolution", "draft")},
            }
        if persistence_enabled:
            update_workflow(
                str(state["workflow_id"]),
                status=status,
                summary=summary,
                classification=state.get("classification"),
                proposal_id=(state.get("proposal") or {}).get("proposal_id"),
                error_code=state.get("error_code"),
                stage="workflow",
                event_type="workflow_finished" if status != "pending_approval" else "workflow_paused",
                event_details={"status": status},
            )
        return {"status": status}

    def assess_request_node(state: Mapping[str, Any]) -> dict[str, Any]:
        working = dict(state)
        with audit_batch(str(state["workflow_id"])):
            working.update(input_node(working))
            if not working.get("input_error_code"):
                working.update(triage_node(working))
                working.update(supervisor_node(working))
                if select_route(working) == "read_only_order":
                    event(working, "order_delivery", "read_only_investigation_started")
        return working

    def select_route(state: Mapping[str, Any]) -> str:
        if state.get("input_error_code"):
            return "safe_fallback"
        classification = state.get("classification") or {}
        if (state.get("triage_ready") is True
            and state.get("specialist") == "order_delivery"
            and classification.get("intent") == "order_status"
            and classification.get("classifier_provider") == "deterministic_rule"
            and "model_safety_check_passed" in (classification.get("risk_flags") or [])):
            return "read_only_order"
        return str(state.get("specialist") or "manual_review")

    def read_only_order_node(state: Mapping[str, Any]) -> dict[str, Any]:
        # These stages have no external mutations or approval interrupts. Retry
        # may replay the whole node; preserve checks and audit entries while
        # checkpointing only the completed evidence/answer boundary.
        working = dict(state)
        with audit_batch(str(state["workflow_id"])):
            working.update(specialist_node(working, "order_delivery", order_delivery_specialist))
            working.update(consolidate_node(working))
            if not working.get("specialist_error_code"):
                working.update(resolution_node(working))
                if (working.get("resolution") or {}).get("outcome") == "answer":
                    working.update(draft_node(working))
                    working.update(validate_node(working))
            if working.get("status") != "answer_ready":
                working.update(fallback_node(working))
        return working

    builder = StateGraph(WorkflowState)
    builder.add_node("assess_request", assess_request_node)
    builder.add_node("read_only_order", read_only_order_node)
    builder.add_node("prepare_input", input_node)
    builder.add_node("triage", triage_node)
    builder.add_node("supervisor", supervisor_node)
    builder.add_node("policy_faq", lambda state: specialist_node(state, "policy_faq", policy_faq_specialist))
    builder.add_node("order_delivery", lambda state: specialist_node(state, "order_delivery", order_delivery_specialist))
    builder.add_node("return_refund", lambda state: specialist_node(state, "return_refund", return_refund_specialist))
    builder.add_node("loyalty_rewards", lambda state: specialist_node(state, "loyalty_rewards", loyalty_rewards_specialist))
    builder.add_node("product_issue", lambda state: specialist_node(state, "product_issue", product_issue_specialist))
    builder.add_node("manual_review", fallback_node)
    builder.add_node("consolidate_evidence", consolidate_node)
    builder.add_node("deterministic_rules", resolution_node)
    builder.add_node("draft_response", draft_node)
    builder.add_node("validate_response", validate_node)
    builder.add_node("safe_fallback", fallback_node)
    builder.add_node("persist_proposal", proposal_node)
    builder.add_node("approval_interrupt", approval_node)
    builder.add_node("finalize", finalize_node)

    builder.add_edge(START, "assess_request")
    builder.add_conditional_edges("assess_request", select_route, {
        name: name for name in ("read_only_order", "policy_faq", "order_delivery", "return_refund",
                                "loyalty_rewards", "product_issue", "manual_review", "safe_fallback")
    })
    builder.add_edge("read_only_order", "finalize")
    # Retain old node names/edges so an existing checkpoint can still resume.
    builder.add_conditional_edges(
        "prepare_input",
        lambda state: "fallback" if state.get("input_error_code") else "triage",
        {"fallback": "safe_fallback", "triage": "triage"},
    )
    builder.add_edge("triage", "supervisor")
    builder.add_conditional_edges(
        "supervisor",
        lambda state: state.get("specialist", "manual_review"),
        {
            "policy_faq": "policy_faq",
            "order_delivery": "order_delivery",
            "return_refund": "return_refund",
            "loyalty_rewards": "loyalty_rewards",
            "product_issue": "product_issue",
            "manual_review": "manual_review",
        },
    )
    for specialist in ("policy_faq", "order_delivery", "return_refund", "product_issue", "loyalty_rewards"):
        builder.add_edge(specialist, "consolidate_evidence")
    builder.add_conditional_edges(
        "consolidate_evidence",
        lambda state: "fallback" if state.get("specialist_error_code") else "rules",
        {"fallback": "safe_fallback", "rules": "deterministic_rules"},
    )
    builder.add_conditional_edges(
        "deterministic_rules",
        lambda state: (state.get("resolution") or {}).get("outcome", "escalate"),
        {"answer": "draft_response", "proposal": "persist_proposal", "needs_information": "safe_fallback", "escalate": "safe_fallback"},
    )
    builder.add_edge("draft_response", "validate_response")
    builder.add_conditional_edges(
        "validate_response",
        lambda state: "valid" if not state.get("validation_errors") else "invalid",
        {"valid": "finalize", "invalid": "safe_fallback"},
    )
    builder.add_edge("persist_proposal", "approval_interrupt")
    builder.add_edge("approval_interrupt", "finalize")
    builder.add_edge("manual_review", "finalize")
    builder.add_edge("safe_fallback", "finalize")
    builder.add_edge("finalize", END)
    return builder.compile(checkpointer=checkpointer)


def get_workflow_graph():
    """Return the process-wide graph backed by the dedicated Postgres checkpointer."""
    global _GRAPH, _CHECKPOINT_POOL, _CHECKPOINT_DSN
    dsn = os.getenv("WORKFLOW_DATABASE_URL", "").strip()
    if not dsn:
        raise WorkflowStoreUnavailable("WORKFLOW_DATABASE_URL is not configured")
    with _GRAPH_LOCK:
        if _GRAPH is not None and _CHECKPOINT_DSN == dsn:
            return _GRAPH
        close_workflow_graph()
        try:
            from langgraph.checkpoint.postgres import PostgresSaver
            from psycopg_pool import ConnectionPool
            import psycopg
            from psycopg.rows import dict_row

            os.environ.setdefault("LANGGRAPH_STRICT_MSGPACK", "true")
            _CHECKPOINT_POOL = ConnectionPool[psycopg.Connection[dict[str, Any]]](
                conninfo=dsn,
                min_size=1,
                max_size=4,
                kwargs={"connect_timeout": 5, "application_name": "agentic-support-langgraph-checkpointer",
                        "autocommit": True, "prepare_threshold": 0, "row_factory": dict_row},
                open=True,
            )
            checkpointer = PostgresSaver(_CHECKPOINT_POOL)
            _GRAPH = build_workflow_graph(checkpointer=checkpointer, persistence_enabled=True)
            _CHECKPOINT_DSN = dsn
            return _GRAPH
        except Exception as exc:
            if _CHECKPOINT_POOL is not None:
                _CHECKPOINT_POOL.close()
            _CHECKPOINT_POOL = None
            _GRAPH = None
            _CHECKPOINT_DSN = None
            raise WorkflowStoreUnavailable("Persistent LangGraph checkpoint service is unavailable") from exc


def close_workflow_graph() -> None:
    global _GRAPH, _CHECKPOINT_POOL, _CHECKPOINT_DSN
    with _GRAPH_LOCK:
        if _CHECKPOINT_POOL is not None:
            _CHECKPOINT_POOL.close()
        _GRAPH = None
        _CHECKPOINT_POOL = None
        _CHECKPOINT_DSN = None
