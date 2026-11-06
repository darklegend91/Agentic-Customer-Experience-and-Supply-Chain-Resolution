"""PostgreSQL persistence for workflow summaries, proposals, decisions, and audit."""

from __future__ import annotations

import hashlib
import json
import os
import uuid
import atexit
from threading import RLock
from contextlib import contextmanager, ExitStack
from datetime import date, datetime
from typing import Any, Generator

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from psycopg_pool import ConnectionPool

from ..runtime import LocalDevelopmentOnly, require_local_development


class WorkflowStoreUnavailable(RuntimeError):
    """The dedicated write-enabled workflow database is unavailable."""


class WorkflowNotFound(LookupError):
    """A requested workflow or proposal does not exist."""


class WorkflowConflict(RuntimeError):
    """The requested workflow transition conflicts with stored state."""


_POOL_LOCK = RLock()
_POOL: ConnectionPool[psycopg.Connection[dict[str, Any]]] | None = None
_POOL_DSN: str | None = None


def close_workflow_pool() -> None:
    global _POOL, _POOL_DSN
    with _POOL_LOCK:
        if _POOL is not None:
            _POOL.close()
        _POOL = None
        _POOL_DSN = None


def _get_pool() -> ConnectionPool[psycopg.Connection[dict[str, Any]]]:
    global _POOL, _POOL_DSN
    dsn = _dsn()
    with _POOL_LOCK:
        if _POOL is None or _POOL_DSN != dsn:
            close_workflow_pool()
            _POOL = ConnectionPool[psycopg.Connection[dict[str, Any]]](
                conninfo=dsn,
                min_size=1,
                max_size=8,
                timeout=10,
                kwargs={
                    "connect_timeout": 5,
                    "application_name": "agentic-customer-support-workflow",
                    "row_factory": dict_row,
                },
                open=True,
            )
            _POOL_DSN = dsn
        return _POOL


atexit.register(close_workflow_pool)


def _dsn() -> str:
    try:
        require_local_development()
    except LocalDevelopmentOnly as exc:
        raise WorkflowStoreUnavailable(str(exc)) from exc
    dsn = os.getenv("WORKFLOW_DATABASE_URL", "").strip()
    if not dsn:
        raise WorkflowStoreUnavailable("WORKFLOW_DATABASE_URL is not configured")
    return dsn


@contextmanager
def _connection(*, pipelined: bool = False) -> Generator[psycopg.Connection[dict[str, Any]], None, None]:
    try:
        # Pool context commits on success, rolls back on error, and returns the
        # connection. Approval writes retain the same transaction boundaries.
        with _get_pool().connection() as connection:
            with ExitStack() as stack:
                if pipelined:
                    # Audit-only inserts need no intermediate results. Send
                    # BEGIN, timeout, INSERT and COMMIT in one network batch;
                    # flush/commit failures still propagate to the worker.
                    stack.enter_context(connection.pipeline())
                    stack.enter_context(connection.transaction())
                connection.execute("SET LOCAL statement_timeout = '5000ms'")
                yield connection
    except (WorkflowStoreUnavailable, WorkflowNotFound, WorkflowConflict):
        raise
    except Exception as exc:
        raise WorkflowStoreUnavailable("Workflow database operation failed") from exc


def _as_iso(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return value


def _row_dict(row: Any) -> dict[str, Any] | None:
    if row is None:
        return None
    return {key: _as_iso(value) for key, value in dict(row).items()}


def _uuid(value: str | uuid.UUID) -> uuid.UUID:
    try:
        return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))
    except (ValueError, TypeError, AttributeError) as exc:
        raise ValueError("Workflow identifiers must be UUIDs") from exc


def create_workflow_run(
    *,
    workflow_id: str,
    thread_id: str,
    request_id: str,
    created_by: str,
    ticket_id: str | None,
    order_id: str | None,
    job_payload: dict[str, Any] | None = None,
) -> None:
    with _connection() as connection:
        connection.execute(
            """
            INSERT INTO workflow_runs
                (workflow_id, thread_id, request_id, created_by, ticket_id, order_id, status)
            VALUES (%s, %s, %s, %s, %s, %s, 'running')
            """,
            (_uuid(workflow_id), _uuid(thread_id), request_id, created_by, ticket_id, order_id),
        )
        _insert_event(
            connection,
            workflow_id=workflow_id,
            stage="intake",
            event_type="workflow_queued" if job_payload is not None else "workflow_started",
            actor_id=created_by,
            details={"ticket_reference_present": bool(ticket_id), "order_reference_present": bool(order_id)},
        )
        if job_payload is not None:
            connection.execute(
                """
                INSERT INTO workflow_jobs (workflow_id, payload_json)
                VALUES (%s, %s)
                """,
                (_uuid(workflow_id), Jsonb(job_payload)),
            )


def claim_workflow_job(worker_id: str, *, lease_seconds: int = 180) -> dict[str, Any] | None:
    """Atomically claim the next queued job, reclaiming work from expired leases."""
    with _connection() as connection:
        exhausted = connection.execute(
            """
            UPDATE workflow_jobs
            SET status = 'failed', payload_json = '{}'::jsonb,
                worker_id = NULL, lease_until = NULL, updated_at = now()
            WHERE attempts >= max_attempts
              AND (status = 'queued' OR (status = 'running' AND lease_until <= now()))
            RETURNING workflow_id, max_attempts
            """
        ).fetchall()
        for row in exhausted:
            workflow_id = str(row["workflow_id"])
            summary = {
                "status": "failed_safe",
                "answer": "The investigation could not be resumed safely. Please route this case to human support.",
                "error_code": "workflow_retry_limit_exceeded",
                "reason_codes": ["workflow_retry_limit_exceeded"],
                "evidence_refs": [],
                "missing_information": [],
            }
            connection.execute(
                """
                UPDATE workflow_runs
                SET status = 'failed_safe', summary_json = %s, error_code = 'workflow_retry_limit_exceeded', updated_at = now()
                WHERE workflow_id = %s AND status = 'running'
                """,
                (Jsonb(summary), _uuid(workflow_id)),
            )
            _insert_event(
                connection,
                workflow_id=workflow_id,
                stage="worker",
                event_type="workflow_retry_limit_exceeded",
                details={"attempt_limit": int(row["max_attempts"])},
            )

        row = connection.execute(
            """
            WITH candidate AS (
                SELECT workflow_id
                FROM workflow_jobs
                WHERE attempts < max_attempts
                  AND ((status = 'queued' AND available_at <= now())
                    OR (status = 'running' AND lease_until <= now()))
                ORDER BY available_at, created_at
                FOR UPDATE SKIP LOCKED
                LIMIT 1
            )
            UPDATE workflow_jobs AS job
            SET status = 'running',
                attempts = job.attempts + 1,
                worker_id = %s,
                lease_until = now() + (%s * interval '1 second'),
                updated_at = now()
            FROM candidate
            WHERE job.workflow_id = candidate.workflow_id
            RETURNING job.workflow_id, job.payload_json, job.attempts
            """,
            (worker_id, max(30, int(lease_seconds))),
        ).fetchone()
        if row is None:
            return None
        workflow_id = str(row["workflow_id"])
        _insert_event(
            connection,
            workflow_id=workflow_id,
            stage="worker",
            event_type="workflow_worker_claimed",
            details={"attempt": int(row["attempts"])},
        )
        return {
            "workflow_id": workflow_id,
            "payload": row["payload_json"],
            "attempt": int(row["attempts"]),
        }


def renew_workflow_job(workflow_id: str, worker_id: str, *, lease_seconds: int = 180) -> bool:
    with _connection() as connection:
        row = connection.execute(
            """
            UPDATE workflow_jobs
            SET lease_until = now() + (%s * interval '1 second'), updated_at = now()
            WHERE workflow_id = %s AND status = 'running' AND worker_id = %s
            RETURNING workflow_id
            """,
            (max(30, int(lease_seconds)), _uuid(workflow_id), worker_id),
        ).fetchone()
        return row is not None


def complete_workflow_job(workflow_id: str, worker_id: str) -> None:
    with _connection() as connection:
        row = connection.execute(
            """
            UPDATE workflow_jobs
            SET status = 'completed', payload_json = '{}'::jsonb,
                worker_id = NULL, lease_until = NULL, updated_at = now()
            WHERE workflow_id = %s AND status = 'running' AND worker_id = %s
            RETURNING workflow_id
            """,
            (_uuid(workflow_id), worker_id),
        ).fetchone()
        if row is None:
            raise WorkflowConflict("Workflow job lease was lost before completion")


def retry_workflow_job(
    workflow_id: str,
    worker_id: str,
    *,
    error_type: str,
    delay_seconds: int,
) -> None:
    """Release a failed job for bounded retry without logging exception contents."""
    with _connection() as connection:
        row = connection.execute(
            """
            UPDATE workflow_jobs
            SET status = 'queued',
                worker_id = NULL,
                lease_until = NULL,
                available_at = now() + (%s * interval '1 second'),
                last_error_type = %s,
                updated_at = now()
            WHERE workflow_id = %s AND status = 'running' AND worker_id = %s
            RETURNING workflow_id
            """,
            (max(1, int(delay_seconds)), error_type[:128], _uuid(workflow_id), worker_id),
        ).fetchone()
        if row is None:
            raise WorkflowConflict("Workflow job lease was lost before retry scheduling")
        _insert_event(
            connection,
            workflow_id=workflow_id,
            stage="worker",
            event_type="workflow_retry_scheduled",
            details={"error_type": error_type[:128], "delay_seconds": max(1, int(delay_seconds))},
        )


def _insert_event(
    connection: psycopg.Connection[dict[str, Any]],
    *,
    workflow_id: str,
    stage: str,
    event_type: str,
    actor_id: str | None = None,
    details: dict[str, Any] | None = None,
    occurred_at: datetime | None = None,
) -> None:
    connection.execute(
        """
        INSERT INTO workflow_events (event_id, workflow_id, stage, event_type, actor_id, details_json, occurred_at)
        VALUES (%s, %s, %s, %s, %s, %s, COALESCE(%s, clock_timestamp()))
        """,
        (uuid.uuid4(), _uuid(workflow_id), stage, event_type, actor_id, Jsonb(details or {}), occurred_at),
    )


def record_stage_events(workflow_id: str, events: list[dict[str, Any]]) -> None:
    """Atomically persist a replayable node's audit trail in one round trip."""
    if not events:
        return
    with _connection(pipelined=True) as connection:
        for entry in events:
            _insert_event(connection, workflow_id=workflow_id, **entry)


def record_stage_event(
    workflow_id: str,
    *,
    stage: str,
    event_type: str,
    details: dict[str, Any] | None = None,
) -> None:
    with _connection(pipelined=True) as connection:
        _insert_event(
            connection,
            workflow_id=workflow_id,
            stage=stage,
            event_type=event_type,
            details=details,
        )


def update_workflow_order_scope(workflow_id: str, *, order_id: str) -> None:
    """Persist an order ID resolved from a ticket before exposing workflow evidence."""
    with _connection() as connection:
        cursor = connection.execute(
            """
            UPDATE workflow_runs
            SET order_id = %s, updated_at = now()
            WHERE workflow_id = %s
            RETURNING workflow_id
            """,
            (order_id, _uuid(workflow_id)),
        )
        if cursor.fetchone() is None:
            raise WorkflowNotFound("Workflow was not found while recording resolved order scope")


def update_workflow(
    workflow_id: str,
    *,
    status: str,
    summary: dict[str, Any] | None = None,
    classification: dict[str, Any] | None = None,
    proposal_id: str | None = None,
    error_code: str | None = None,
    stage: str | None = None,
    event_type: str | None = None,
    event_details: dict[str, Any] | None = None,
) -> None:
    summary_json = Jsonb(summary) if summary is not None else None
    classification_json = Jsonb(classification) if classification is not None else None
    with _connection() as connection:
        cursor = connection.execute(
            """
            UPDATE workflow_runs
            SET status = %s,
                summary_json = COALESCE(%s, summary_json),
                classification_json = COALESCE(%s, classification_json),
                proposal_id = COALESCE(%s, proposal_id),
                error_code = %s,
                updated_at = now()
            WHERE workflow_id = %s
            RETURNING workflow_id
            """,
            (status, summary_json, classification_json, _uuid(proposal_id) if proposal_id else None,
             error_code, _uuid(workflow_id)),
        )
        if cursor.fetchone() is None:
            raise WorkflowNotFound("Workflow was not found")
        if stage and event_type:
            _insert_event(
                connection,
                workflow_id=workflow_id,
                stage=stage,
                event_type=event_type,
                details=event_details,
            )


def save_proposal(
    *,
    proposal_id: str,
    workflow_id: str,
    action_kind: str,
    summary: str,
    permitted_options: list[str],
    evidence_refs: list[str],
    policy_versions: list[str],
    evidence_fingerprint: str,
    proposal_payload: dict[str, Any],
    workflow_summary: dict[str, Any],
    classification: dict[str, Any] | None,
) -> None:
    with _connection() as connection:
        connection.execute(
            """
            INSERT INTO workflow_proposals
                (proposal_id, workflow_id, proposal_version, status, action_kind, summary,
                 permitted_options, evidence_refs, policy_versions, evidence_fingerprint, payload_json)
            VALUES (%s, %s, 1, 'pending_approval', %s, %s, %s, %s, %s, %s, %s)
            """,
            (_uuid(proposal_id), _uuid(workflow_id), action_kind, summary,
             Jsonb(permitted_options), Jsonb(evidence_refs), Jsonb(policy_versions),
             evidence_fingerprint, Jsonb(proposal_payload)),
        )
        cursor = connection.execute(
            """
            UPDATE workflow_runs
            SET status = 'pending_approval',
                proposal_id = %s,
                summary_json = %s,
                classification_json = COALESCE(%s, classification_json),
                updated_at = now()
            WHERE workflow_id = %s
            """,
            (_uuid(proposal_id), Jsonb(workflow_summary),
             Jsonb(classification) if classification is not None else None, _uuid(workflow_id)),
        )
        if cursor.rowcount != 1:
            raise WorkflowNotFound("Workflow was not found while persisting the proposal")
        _insert_event(
            connection,
            workflow_id=workflow_id,
            stage="proposal",
            event_type="proposal_paused_for_approval",
            details={"proposal_id": proposal_id, "action_kind": action_kind, "proposal_version": 1},
        )


def get_workflow(workflow_id: str) -> dict[str, Any]:
    with _connection() as connection:
        row = connection.execute(
            "SELECT * FROM workflow_runs WHERE workflow_id = %s",
            (_uuid(workflow_id),),
        ).fetchone()
    result = _row_dict(row)
    if result is None:
        raise WorkflowNotFound("Workflow was not found")
    return result


def get_proposal(proposal_id: str) -> dict[str, Any]:
    with _connection() as connection:
        row = connection.execute(
            """
            SELECT p.*, r.thread_id, r.created_by, r.order_id, r.ticket_id
            FROM workflow_proposals p
            JOIN workflow_runs r ON r.workflow_id = p.workflow_id
            WHERE p.proposal_id = %s
            """,
            (_uuid(proposal_id),),
        ).fetchone()
    result = _row_dict(row)
    if result is None:
        raise WorkflowNotFound("Proposal was not found")
    return result


def list_workflow_events(workflow_id: str, *, limit: int = 100) -> list[dict[str, Any]]:
    if not 1 <= limit <= 200:
        raise ValueError("Event limit must be between 1 and 200")
    with _connection() as connection:
        exists = connection.execute(
            "SELECT 1 FROM workflow_runs WHERE workflow_id = %s",
            (_uuid(workflow_id),),
        ).fetchone()
        if exists is None:
            raise WorkflowNotFound("Workflow was not found")
        rows = connection.execute(
            """
            SELECT event_id, workflow_id, stage, event_type, actor_id, occurred_at, details_json
            FROM workflow_events
            WHERE workflow_id = %s
            ORDER BY occurred_at, event_id
            LIMIT %s
            """,
            (_uuid(workflow_id), limit),
        ).fetchall()
    return [_row_dict(row) or {} for row in rows]


def record_approval_decision(
    *,
    proposal_id: str,
    decision: str,
    actor_id: str,
    expected_version: int,
    idempotency_key: str,
    comment: str | None,
) -> dict[str, Any]:
    if decision not in {"approve", "reject"}:
        raise ValueError("Decision must be approve or reject")
    if not 1 <= len(idempotency_key) <= 128:
        raise ValueError("Idempotency-Key must be between 1 and 128 characters")
    with _connection() as connection:
        connection.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
            (idempotency_key,),
        )
        existing = connection.execute(
            "SELECT * FROM workflow_decisions WHERE idempotency_key = %s FOR UPDATE",
            (idempotency_key,),
        ).fetchone()
        if existing is not None:
            current = _row_dict(existing) or {}
            same_request = (
                str(current["proposal_id"]) == str(_uuid(proposal_id))
                and current["decision"] == decision
                and current["actor_id"] == actor_id
                and current["expected_proposal_version"] == expected_version
            )
            if not same_request:
                raise WorkflowConflict("Idempotency-Key was already used for a different decision")
            proposal = connection.execute(
                """
                SELECT p.*, r.thread_id, r.workflow_id, r.order_id, r.ticket_id, r.created_by
                FROM workflow_proposals p
                JOIN workflow_runs r ON r.workflow_id = p.workflow_id
                WHERE p.proposal_id = %s
                """,
                (_uuid(proposal_id),),
            ).fetchone()
            if proposal is None:
                raise WorkflowNotFound("Proposal was not found")
            return {"decision": current, "proposal": _row_dict(proposal), "is_replay": True}

        proposal = connection.execute(
            """
            SELECT p.*, r.thread_id, r.workflow_id, r.order_id, r.ticket_id, r.created_by
            FROM workflow_proposals p
            JOIN workflow_runs r ON r.workflow_id = p.workflow_id
            WHERE p.proposal_id = %s
            FOR UPDATE OF p
            """,
            (_uuid(proposal_id),),
        ).fetchone()
        if proposal is None:
            raise WorkflowNotFound("Proposal was not found")
        proposal_row = _row_dict(proposal) or {}
        if proposal_row["status"] != "pending_approval":
            raise WorkflowConflict("Proposal is no longer pending approval")
        if proposal_row["proposal_version"] != expected_version:
            raise WorkflowConflict("Proposal version changed; refresh the proposal before deciding")

        decision_id = uuid.uuid4()
        connection.execute(
            """
            INSERT INTO workflow_decisions
                (decision_id, proposal_id, workflow_id, idempotency_key, actor_id, decision,
                 expected_proposal_version, comment, status)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'pending')
            """,
            (decision_id, _uuid(proposal_id), _uuid(str(proposal_row["workflow_id"])),
             idempotency_key, actor_id, decision, expected_version, comment),
        )
        connection.execute(
            "UPDATE workflow_proposals SET status = 'decision_recorded', updated_at = now() WHERE proposal_id = %s",
            (_uuid(proposal_id),),
        )
        _insert_event(
            connection,
            workflow_id=str(proposal_row["workflow_id"]),
            stage="approval",
            event_type="approval_decision_recorded",
            actor_id=actor_id,
            details={"proposal_id": proposal_id, "decision": decision, "proposal_version": expected_version},
        )
        return {
            "decision": {
                "decision_id": str(decision_id),
                "proposal_id": proposal_id,
                "workflow_id": str(proposal_row["workflow_id"]),
                "idempotency_key": idempotency_key,
                "actor_id": actor_id,
                "decision": decision,
                "expected_proposal_version": expected_version,
                "comment": comment,
                "status": "pending",
            },
            "proposal": {**proposal_row, "status": "decision_recorded"},
            "is_replay": False,
        }


def complete_approval_decision(
    *,
    proposal_id: str,
    workflow_id: str,
    idempotency_key: str,
    proposal_status: str,
    workflow_status: str,
    summary: dict[str, Any],
    event_type: str,
    actor_id: str,
) -> None:
    allowed = {"approved_simulation", "rejected", "invalidated"}
    if proposal_status not in allowed:
        raise ValueError("Invalid final proposal status")
    with _connection() as connection:
        cursor = connection.execute(
            """
            UPDATE workflow_proposals
            SET status = %s, updated_at = now()
            WHERE proposal_id = %s AND workflow_id = %s
            RETURNING proposal_id
            """,
            (proposal_status, _uuid(proposal_id), _uuid(workflow_id)),
        )
        if cursor.fetchone() is None:
            raise WorkflowNotFound("Proposal was not found")
        decision_cursor = connection.execute(
            """
            UPDATE workflow_decisions
            SET status = 'completed', result_json = %s, completed_at = now()
            WHERE idempotency_key = %s AND proposal_id = %s AND status = 'pending'
            RETURNING decision_id
            """,
            (Jsonb({"proposal_status": proposal_status, "workflow_status": workflow_status}),
             idempotency_key, _uuid(proposal_id)),
        )
        if decision_cursor.fetchone() is None:
            raise WorkflowConflict("Approval decision is not pending completion")
        connection.execute(
            """
            UPDATE workflow_runs
            SET status = %s, summary_json = %s, updated_at = now()
            WHERE workflow_id = %s
            """,
            (workflow_status, Jsonb(summary), _uuid(workflow_id)),
        )
        _insert_event(
            connection,
            workflow_id=workflow_id,
            stage="approval",
            event_type=event_type,
            actor_id=actor_id,
            details={"proposal_id": proposal_id, "proposal_status": proposal_status},
        )


def evidence_fingerprint(evidence: dict[str, Any]) -> str:
    """Hash source facts and policy versions, excluding transient timestamps and scores."""
    order = evidence.get("order") or {}
    stable_order = {
        key: value
        for key, value in order.items()
        if key not in {"as_of", "request_id"}
    }
    stable_policy: list[dict[str, Any]] = []
    policy = evidence.get("policy") or {}
    for method, hits in sorted((policy.get("results") or {}).items()):
        for hit in hits or []:
            stable_policy.append({
                "method": method,
                "document_id": hit.get("document_id"),
                "policy_id": hit.get("policy_id"),
                "policy_version": hit.get("policy_version"),
                "section_id": hit.get("section_id"),
                "chunk_id": hit.get("chunk_id"),
                "source_file_sha256": hit.get("source_file_sha256"),
                "excerpt": hit.get("excerpt"),
                "status": hit.get("status"),
                "marketplace": hit.get("marketplace"),
                "environment_scope": hit.get("environment_scope"),
            })
    stable_policy.sort(key=lambda row: (str(row.get("document_id")), str(row.get("chunk_id")), str(row.get("method"))))
    canonical = json.dumps(
        {"order": stable_order, "policy": stable_policy},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
