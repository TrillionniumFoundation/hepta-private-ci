CREATE TABLE automation_meta (
    singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
    schema_version INTEGER NOT NULL,
    owner_agent_id TEXT NOT NULL
);

CREATE TRIGGER automation_meta_no_update
BEFORE UPDATE ON automation_meta
BEGIN
    SELECT RAISE(ABORT, 'automation owner metadata is immutable');
END;

CREATE TRIGGER automation_meta_no_delete
BEFORE DELETE ON automation_meta
BEGIN
    SELECT RAISE(ABORT, 'automation owner metadata is immutable');
END;

CREATE TABLE automation_tasks (
    task_id TEXT PRIMARY KEY,
    owner_agent_id TEXT NOT NULL,
    thread_id TEXT NOT NULL,
    prompt TEXT NOT NULL,
    schedule_kind TEXT NOT NULL CHECK (schedule_kind IN ('once', 'fixed_interval')),
    interval_ms INTEGER,
    state TEXT NOT NULL CHECK (state IN ('enabled', 'disabled', 'cancelled', 'completed')),
    next_run_at_ms INTEGER,
    next_occurrence INTEGER NOT NULL,
    created_at_ms INTEGER NOT NULL,
    updated_at_ms INTEGER NOT NULL,
    CHECK (
        (schedule_kind = 'once' AND interval_ms IS NULL)
        OR (schedule_kind = 'fixed_interval' AND interval_ms IS NOT NULL AND interval_ms > 0)
    )
);

CREATE TABLE automation_runs (
    task_id TEXT NOT NULL REFERENCES automation_tasks(task_id),
    occurrence INTEGER NOT NULL,
    scheduled_for_ms INTEGER NOT NULL,
    client_user_message_id TEXT NOT NULL UNIQUE,
    state TEXT NOT NULL CHECK (state IN ('pending', 'leased', 'submitted', 'cancelled')),
    lease_generation INTEGER,
    lease_token TEXT,
    lease_expires_at_ms INTEGER,
    queued_submission_id TEXT,
    submitted_at_ms INTEGER,
    PRIMARY KEY(task_id, occurrence),
    CHECK (
        (state = 'leased' AND lease_generation IS NOT NULL AND lease_token IS NOT NULL AND lease_expires_at_ms IS NOT NULL)
        OR (state != 'leased' AND lease_generation IS NULL AND lease_token IS NULL AND lease_expires_at_ms IS NULL)
    )
);

CREATE INDEX automation_due_idx
    ON automation_tasks(state, next_run_at_ms, task_id);

CREATE INDEX automation_recovery_idx
    ON automation_runs(state, lease_generation, lease_expires_at_ms);
