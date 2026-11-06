"""Apply workflow tables and initialize LangGraph's Postgres checkpoints once."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import psycopg

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.app.runtime import require_local_development


MIGRATION = PROJECT_ROOT / "backend" / "app" / "db" / "migrations" / "001_workflow_storage.sql"
JOB_QUEUE_MIGRATION = PROJECT_ROOT / "backend" / "app" / "db" / "migrations" / "003_workflow_job_queue.sql"


def main() -> None:
    require_local_development()
    dsn = os.getenv("WORKFLOW_DATABASE_URL", "").strip()
    if not dsn:
        raise SystemExit("Set WORKFLOW_DATABASE_URL to a dedicated write-enabled workflow database URL.")

    statements = []
    for migration in (MIGRATION, JOB_QUEUE_MIGRATION):
        sql = migration.read_text(encoding="utf-8")
        statements.extend(statement.strip() for statement in sql.split(";") if statement.strip())
    try:
        with psycopg.connect(
            dsn,
            autocommit=True,
            connect_timeout=5,
            application_name="agentic-customer-support-workflow-setup",
        ) as connection:
            for statement in statements:
                connection.execute(statement)
    except Exception as exc:
        raise SystemExit("Workflow storage migration failed; no credentials or SQL details were logged.") from exc

    # Import after APP_ENV/DATABASE_URL are loaded to keep this a one-shot setup task.
    os.environ.setdefault("LANGGRAPH_STRICT_MSGPACK", "true")
    from langgraph.checkpoint.postgres import PostgresSaver

    try:
        with PostgresSaver.from_conn_string(dsn) as checkpointer:
            checkpointer.setup()
    except Exception as exc:
        raise SystemExit("LangGraph checkpoint setup failed; inspect database permissions and connectivity.") from exc
    print("Workflow tables, durable job queue, and LangGraph checkpoint tables are ready.")


if __name__ == "__main__":
    main()
