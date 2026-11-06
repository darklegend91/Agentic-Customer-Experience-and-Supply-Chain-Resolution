CREATE TABLE IF NOT EXISTS workflow_jobs (
    workflow_id UUID PRIMARY KEY REFERENCES workflow_runs(workflow_id) ON DELETE CASCADE,
    payload_json JSONB NOT NULL,
    status VARCHAR(16) NOT NULL DEFAULT 'queued'
        CHECK (status IN ('queued', 'running', 'completed', 'failed')),
    attempts INTEGER NOT NULL DEFAULT 0 CHECK (attempts >= 0),
    max_attempts INTEGER NOT NULL DEFAULT 5 CHECK (max_attempts BETWEEN 1 AND 10),
    available_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    lease_until TIMESTAMPTZ,
    worker_id VARCHAR(160),
    last_error_type VARCHAR(128),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (
        (status = 'running' AND worker_id IS NOT NULL AND lease_until IS NOT NULL)
        OR (status <> 'running' AND worker_id IS NULL AND lease_until IS NULL)
    )
);

CREATE INDEX IF NOT EXISTS workflow_jobs_ready_idx
    ON workflow_jobs (status, available_at, created_at);

CREATE INDEX IF NOT EXISTS workflow_jobs_lease_idx
    ON workflow_jobs (lease_until)
    WHERE status = 'running';
