"""Durable PostgreSQL-backed LangGraph workflow worker for private deployments."""

from __future__ import annotations

import logging
import os
import signal
import socket
import threading
import uuid
from typing import Any

from .approval.service import execute_workflow
from .approval.workflow_state import (
    WorkflowStoreUnavailable,
    claim_workflow_job,
    complete_workflow_job,
    renew_workflow_job,
    retry_workflow_job,
)
from .observability.logging import log_safe_error
from .runtime import load_project_environment, require_local_development

logger = logging.getLogger("agentic_customer_support.worker")
_stop = threading.Event()


def _request_id(payload: Any) -> str:
    if isinstance(payload, dict):
        return str(payload.get("request_id") or "unavailable")
    return "unavailable"


def _heartbeat(workflow_id: str, worker_id: str, stop: threading.Event, lost: threading.Event) -> None:
    lease_seconds = max(60, int(os.getenv("WORKFLOW_JOB_LEASE_SECONDS", "180")))
    interval = max(10, lease_seconds // 3)
    while not stop.wait(interval):
        try:
            if not renew_workflow_job(workflow_id, worker_id, lease_seconds=lease_seconds):
                lost.set()
                return
        except WorkflowStoreUnavailable as exc:
            log_safe_error(
                logger,
                event="workflow_job_heartbeat_failed",
                request_id="unavailable",
                stage="worker_heartbeat",
                error_type=type(exc).__name__,
            )


def _handle_job(job: dict[str, Any], worker_id: str) -> None:
    workflow_id = str(job["workflow_id"])
    payload = job.get("payload")
    attempt = int(job.get("attempt") or 1)
    request_id = _request_id(payload)
    heartbeat_stop = threading.Event()
    lease_lost = threading.Event()
    heartbeat = threading.Thread(
        target=_heartbeat,
        args=(workflow_id, worker_id, heartbeat_stop, lease_lost),
        name=f"workflow-heartbeat-{workflow_id[:8]}",
        daemon=True,
    )
    heartbeat.start()
    try:
        if not isinstance(payload, dict):
            raise ValueError("Persisted workflow job payload is malformed")
        execute_workflow(payload)
        if lease_lost.is_set():
            return
        complete_workflow_job(workflow_id, worker_id)
    except Exception as exc:
        delay = min(60, 2 ** min(attempt, 6))
        try:
            retry_workflow_job(
                workflow_id,
                worker_id,
                error_type=type(exc).__name__,
                delay_seconds=delay,
            )
        except Exception as retry_exc:
            log_safe_error(
                logger,
                event="workflow_job_retry_persistence_failed",
                request_id=request_id,
                stage="worker_retry",
                error_type=type(retry_exc).__name__,
            )
        log_safe_error(
            logger,
            event="workflow_job_execution_failed",
            request_id=request_id,
            stage="worker_execution",
            error_type=type(exc).__name__,
        )
    finally:
        heartbeat_stop.set()
        heartbeat.join(timeout=2)


def run_worker() -> None:
    load_project_environment()
    require_local_development()
    worker_id = f"{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex[:12]}"
    poll_seconds = max(1, int(os.getenv("WORKFLOW_WORKER_POLL_SECONDS", "2")))
    logger.info("Workflow worker started")

    while not _stop.is_set():
        try:
            job = claim_workflow_job(
                worker_id,
                lease_seconds=max(60, int(os.getenv("WORKFLOW_JOB_LEASE_SECONDS", "180"))),
            )
        except WorkflowStoreUnavailable as exc:
            log_safe_error(
                logger,
                event="workflow_queue_unavailable",
                request_id="unavailable",
                stage="worker_poll",
                error_type=type(exc).__name__,
            )
            _stop.wait(poll_seconds)
            continue

        if job is None:
            _stop.wait(poll_seconds)
            continue
        _handle_job(job, worker_id)

    logger.info("Workflow worker stopped")


def _request_stop(_signum: int, _frame: Any) -> None:
    _stop.set()


def main() -> None:
    logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
    signal.signal(signal.SIGTERM, _request_stop)
    signal.signal(signal.SIGINT, _request_stop)
    run_worker()


if __name__ == "__main__":
    main()
