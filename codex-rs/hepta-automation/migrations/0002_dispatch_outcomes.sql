-- A queue admission can be accepted by the provider while its response is
-- lost.  Keep that ambiguity durable and keyed by the same occurrence/client
-- id so recovery never turns an unknown outcome into a blind duplicate.
CREATE TABLE automation_dispatch_outcomes (
    task_id TEXT NOT NULL,
    occurrence INTEGER NOT NULL,
    client_user_message_id TEXT NOT NULL UNIQUE,
    queued_submission_id TEXT UNIQUE,
    outcome TEXT NOT NULL CHECK (outcome IN ('uncertain', 'submitted')),
    observed_at_ms INTEGER NOT NULL,
    submitted_at_ms INTEGER,
    PRIMARY KEY (task_id, occurrence),
    FOREIGN KEY (task_id, occurrence)
        REFERENCES automation_runs(task_id, occurrence)
);

CREATE INDEX automation_dispatch_outcome_state_idx
    ON automation_dispatch_outcomes(outcome, observed_at_ms, task_id, occurrence);

-- Version metadata is immutable to normal callers, but the migration itself
-- must atomically advance an existing v1 store before the opener verifies it.
DROP TRIGGER automation_meta_no_update;
UPDATE automation_meta SET schema_version = 2 WHERE singleton = 1;
CREATE TRIGGER automation_meta_no_update
BEFORE UPDATE ON automation_meta
BEGIN
    SELECT RAISE(ABORT, 'automation owner metadata is immutable');
END;
