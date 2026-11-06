CREATE TABLE IF NOT EXISTS workflow_runs (
    workflow_id UUID PRIMARY KEY,
    thread_id UUID NOT NULL UNIQUE,
    request_id VARCHAR(128) NOT NULL,
    created_by VARCHAR(128) NOT NULL,
    ticket_id VARCHAR(128),
    order_id VARCHAR(128),
    status VARCHAR(32) NOT NULL CHECK (status IN (
        'running', 'needs_information', 'escalated', 'answer_ready',
        'pending_approval', 'approved_simulation', 'rejected', 'invalidated', 'failed_safe'
    )),
    classification_json JSONB,
    summary_json JSONB,
    proposal_id UUID,
    error_code VARCHAR(96),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS workflow_runs_status_updated_idx
    ON workflow_runs (status, updated_at DESC);

CREATE TABLE IF NOT EXISTS workflow_proposals (
    proposal_id UUID PRIMARY KEY,
    workflow_id UUID NOT NULL REFERENCES workflow_runs(workflow_id),
    proposal_version INTEGER NOT NULL CHECK (proposal_version > 0),
    status VARCHAR(32) NOT NULL CHECK (status IN (
        'pending_approval', 'decision_recorded', 'approved_simulation', 'rejected', 'invalidated'
    )),
    action_kind VARCHAR(64) NOT NULL,
    summary TEXT NOT NULL,
    permitted_options JSONB NOT NULL DEFAULT '[]'::jsonb,
    evidence_refs JSONB NOT NULL DEFAULT '[]'::jsonb,
    policy_versions JSONB NOT NULL DEFAULT '[]'::jsonb,
    evidence_fingerprint CHAR(64) NOT NULL,
    payload_json JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS workflow_proposals_workflow_idx
    ON workflow_proposals (workflow_id, created_at DESC);

CREATE TABLE IF NOT EXISTS workflow_decisions (
    decision_id UUID PRIMARY KEY,
    proposal_id UUID NOT NULL REFERENCES workflow_proposals(proposal_id),
    workflow_id UUID NOT NULL REFERENCES workflow_runs(workflow_id),
    idempotency_key VARCHAR(128) NOT NULL UNIQUE,
    actor_id VARCHAR(128) NOT NULL,
    decision VARCHAR(16) NOT NULL CHECK (decision IN ('approve', 'reject')),
    expected_proposal_version INTEGER NOT NULL CHECK (expected_proposal_version > 0),
    comment VARCHAR(500),
    status VARCHAR(16) NOT NULL CHECK (status IN ('pending', 'completed')),
    result_json JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS workflow_decisions_proposal_idx
    ON workflow_decisions (proposal_id, created_at DESC);

CREATE TABLE IF NOT EXISTS workflow_events (
    event_id UUID PRIMARY KEY,
    workflow_id UUID NOT NULL REFERENCES workflow_runs(workflow_id),
    stage VARCHAR(64) NOT NULL,
    event_type VARCHAR(96) NOT NULL,
    actor_id VARCHAR(128),
    details_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    occurred_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS workflow_events_workflow_time_idx
    ON workflow_events (workflow_id, occurred_at, event_id);
