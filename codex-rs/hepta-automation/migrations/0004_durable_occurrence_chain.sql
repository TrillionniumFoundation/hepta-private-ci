-- Promote automation occurrences and the TaskFlow step outbox into the default
-- durable schema. Existing queue-admission rows are preserved as non-terminal
-- occurrences; they are never re-labelled as successful external effects.

ALTER TABLE automation_tasks
    ADD COLUMN schedule_revision INTEGER NOT NULL DEFAULT 1 CHECK (schedule_revision > 0);
ALTER TABLE automation_tasks
    ADD COLUMN overlap_policy TEXT NOT NULL DEFAULT 'forbid'
        CHECK (overlap_policy IN ('forbid', 'allow'));
ALTER TABLE automation_tasks
    ADD COLUMN missed_run_policy TEXT NOT NULL DEFAULT 'coalesce'
        CHECK (missed_run_policy IN ('skip', 'coalesce', 'bounded_catch_up'));
ALTER TABLE automation_tasks
    ADD COLUMN catch_up_limit INTEGER NOT NULL DEFAULT 1
        CHECK (catch_up_limit BETWEEN 1 AND 1024);
ALTER TABLE automation_tasks
    ADD COLUMN catch_up_remaining INTEGER NOT NULL DEFAULT 0
        CHECK (catch_up_remaining BETWEEN 0 AND 1024);

ALTER TABLE automation_runs ADD COLUMN occurrence_id TEXT;
ALTER TABLE automation_runs ADD COLUMN schedule_revision INTEGER;
ALTER TABLE automation_runs
    ADD COLUMN graph_generation INTEGER NOT NULL DEFAULT 1 CHECK (graph_generation > 0);
ALTER TABLE automation_runs ADD COLUMN taskflow_run_id TEXT;
ALTER TABLE automation_runs ADD COLUMN terminal_state TEXT
    CHECK (terminal_state IS NULL OR terminal_state IN ('succeeded', 'failed', 'cancelled'));
ALTER TABLE automation_runs ADD COLUMN terminal_receipt_digest TEXT
    CHECK (
        terminal_receipt_digest IS NULL OR
        (length(terminal_receipt_digest) = 64
         AND terminal_receipt_digest NOT GLOB '*[^0-9a-f]*')
    );
ALTER TABLE automation_runs ADD COLUMN terminal_at_ms INTEGER
    CHECK (terminal_at_ms IS NULL OR terminal_at_ms >= 0);

-- Legacy rows predate schedule revisions. Preserve their immutable ordering
-- by assigning each historical occurrence its old monotonic occurrence number
-- as a migration revision. The current schedule contract starts after that
-- history, so repeated resume instants cannot collide with historical ids.
UPDATE automation_tasks
SET schedule_revision = CASE
    WHEN next_occurrence > 1 THEN next_occurrence
    ELSE 1
END;

UPDATE automation_runs
SET schedule_revision = occurrence,
    occurrence_id = (
        'hepta.automation.occurrence.v1:' ||
        (SELECT owner_agent_id FROM automation_tasks t WHERE t.task_id = automation_runs.task_id) ||
        ':' || task_id || ':' || occurrence || ':' || scheduled_for_ms
    )
WHERE occurrence_id IS NULL OR schedule_revision IS NULL;

CREATE UNIQUE INDEX automation_runs_occurrence_identity
    ON automation_runs(occurrence_id);
CREATE UNIQUE INDEX automation_runs_taskflow_run
    ON automation_runs(taskflow_run_id)
    WHERE taskflow_run_id IS NOT NULL;
CREATE INDEX automation_runs_terminal_lookup
    ON automation_runs(task_id, terminal_state, scheduled_for_ms);

CREATE TABLE IF NOT EXISTS taskflow_step_outbox (
    owner_agent_id TEXT NOT NULL,
    run_id TEXT NOT NULL,
    step_id TEXT NOT NULL,
    attempt INTEGER NOT NULL CHECK (attempt > 0 AND attempt <= 1000000),
    event_seq INTEGER NOT NULL CHECK (event_seq > 0),
    event_kind TEXT NOT NULL CHECK (
        event_kind IN ('prepared', 'claimed', 'recorded', 'reconciled')
    ),
    command_id TEXT NOT NULL,
    command_digest TEXT NOT NULL CHECK (
        length(command_digest) = 64 AND command_digest NOT GLOB '*[^0-9a-f]*'
    ),
    intent_digest TEXT NOT NULL CHECK (
        length(intent_digest) = 64 AND intent_digest NOT GLOB '*[^0-9a-f]*'
    ),
    payload_digest TEXT NOT NULL CHECK (
        length(payload_digest) = 64 AND payload_digest NOT GLOB '*[^0-9a-f]*'
    ),
    receipt_digest TEXT CHECK (
        receipt_digest IS NULL OR
        (length(receipt_digest) = 64 AND receipt_digest NOT GLOB '*[^0-9a-f]*')
    ),
    observation TEXT CHECK (
        observation IS NULL OR observation IN ('succeeded', 'failed', 'indeterminate')
    ),
    final_outcome TEXT CHECK (
        final_outcome IS NULL OR final_outcome IN ('succeeded', 'failed', 'cancelled')
    ),
    owner_id TEXT NOT NULL,
    owner_epoch INTEGER NOT NULL CHECK (owner_epoch > 0),
    generation INTEGER NOT NULL CHECK (generation > 0),
    fencing_token TEXT NOT NULL CHECK (length(fencing_token) BETWEEN 1 AND 256),
    previous_event_digest TEXT NOT NULL CHECK (
        length(previous_event_digest) = 64 AND
        previous_event_digest NOT GLOB '*[^0-9a-f]*'
    ),
    event_digest TEXT NOT NULL CHECK (
        length(event_digest) = 64 AND event_digest NOT GLOB '*[^0-9a-f]*'
    ),
    recorded_at_ms INTEGER NOT NULL CHECK (recorded_at_ms >= 0),
    PRIMARY KEY (owner_agent_id, run_id, step_id, attempt, event_seq),
    UNIQUE (owner_agent_id, command_id),
    FOREIGN KEY (owner_agent_id, run_id)
        REFERENCES taskflow_runs(owner_agent_id, run_id),
    CHECK (
        (event_kind IN ('prepared', 'claimed') AND
            receipt_digest IS NULL AND observation IS NULL AND final_outcome IS NULL)
        OR
        (event_kind = 'recorded' AND
            receipt_digest IS NOT NULL AND observation IS NOT NULL AND final_outcome IS NULL)
        OR
        (event_kind = 'reconciled' AND
            receipt_digest IS NOT NULL AND observation IS NULL AND final_outcome IS NOT NULL)
    )
);

CREATE TRIGGER IF NOT EXISTS taskflow_step_outbox_no_update
BEFORE UPDATE ON taskflow_step_outbox
BEGIN
    SELECT RAISE(ABORT, 'TaskFlow step outbox is append-only');
END;

CREATE TRIGGER IF NOT EXISTS taskflow_step_outbox_no_delete
BEFORE DELETE ON taskflow_step_outbox
BEGIN
    SELECT RAISE(ABORT, 'TaskFlow step outbox is append-only');
END;

CREATE INDEX IF NOT EXISTS taskflow_step_outbox_lookup
    ON taskflow_step_outbox(owner_agent_id, run_id, step_id, attempt, event_seq);

DROP TRIGGER automation_meta_no_update;
UPDATE automation_meta SET schema_version = 4 WHERE singleton = 1;
CREATE TRIGGER automation_meta_no_update
BEFORE UPDATE ON automation_meta
BEGIN
    SELECT RAISE(ABORT, 'automation owner metadata is immutable');
END;
