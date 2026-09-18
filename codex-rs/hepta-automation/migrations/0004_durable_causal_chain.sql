-- Durable causal-chain ownership for automation occurrences.
--
-- Queue admission remains an admission receipt only.  This schema introduces a
-- distinct durable occurrence lifecycle that can be linked to one TaskFlow run,
-- provider observations, reconciliation and a terminal automation outcome.

ALTER TABLE automation_tasks
    ADD COLUMN schedule_revision INTEGER NOT NULL DEFAULT 1 CHECK (schedule_revision > 0);
ALTER TABLE automation_tasks
    ADD COLUMN missed_run_policy TEXT NOT NULL DEFAULT 'skip'
        CHECK (missed_run_policy IN ('skip', 'coalesce', 'bounded_catch_up'));
ALTER TABLE automation_tasks
    ADD COLUMN catch_up_limit INTEGER NOT NULL DEFAULT 0 CHECK (catch_up_limit BETWEEN 0 AND 1024);
ALTER TABLE automation_tasks
    ADD COLUMN overlap_policy TEXT NOT NULL DEFAULT 'forbid'
        CHECK (overlap_policy IN ('forbid'));

CREATE TABLE automation_occurrences (
    task_id TEXT NOT NULL,
    occurrence INTEGER NOT NULL,
    occurrence_id TEXT NOT NULL UNIQUE,
    schedule_revision INTEGER NOT NULL CHECK (schedule_revision > 0),
    scheduled_for_ms INTEGER NOT NULL,
    lifecycle_state TEXT NOT NULL CHECK (
        lifecycle_state IN (
            'materialized', 'queue_admitted', 'taskflow_running',
            'indeterminate', 'succeeded', 'failed', 'cancelled'
        )
    ),
    taskflow_run_id TEXT,
    queued_submission_id TEXT,
    terminal_reason TEXT,
    created_at_ms INTEGER NOT NULL,
    updated_at_ms INTEGER NOT NULL,
    terminal_at_ms INTEGER,
    PRIMARY KEY (task_id, occurrence),
    FOREIGN KEY (task_id, occurrence)
        REFERENCES automation_runs(task_id, occurrence),
    CHECK (
        (lifecycle_state IN ('succeeded', 'failed', 'cancelled') AND terminal_at_ms IS NOT NULL)
        OR
        (lifecycle_state NOT IN ('succeeded', 'failed', 'cancelled') AND terminal_at_ms IS NULL)
    )
);

CREATE UNIQUE INDEX automation_occurrence_taskflow_run_idx
    ON automation_occurrences(taskflow_run_id)
    WHERE taskflow_run_id IS NOT NULL;

CREATE INDEX automation_occurrence_state_idx
    ON automation_occurrences(task_id, lifecycle_state, scheduled_for_ms, occurrence);

-- Existing stores predate schedule revision.  Revision 1 is therefore the only
-- valid historical binding for backfilled runs.
INSERT INTO automation_occurrences (
    task_id, occurrence, occurrence_id, schedule_revision, scheduled_for_ms,
    lifecycle_state, taskflow_run_id, queued_submission_id, terminal_reason,
    created_at_ms, updated_at_ms, terminal_at_ms
)
SELECT
    r.task_id,
    r.occurrence,
    'hepta.automation.occurrence.v1:' || r.task_id || ':1:' || r.scheduled_for_ms,
    1,
    r.scheduled_for_ms,
    CASE r.state
        WHEN 'submitted' THEN 'queue_admitted'
        WHEN 'cancelled' THEN 'cancelled'
        ELSE 'materialized'
    END,
    NULL,
    r.queued_submission_id,
    CASE WHEN r.state = 'cancelled' THEN 'legacy_cancelled' ELSE NULL END,
    t.created_at_ms,
    COALESCE(r.submitted_at_ms, t.updated_at_ms),
    CASE WHEN r.state = 'cancelled' THEN t.updated_at_ms ELSE NULL END
FROM automation_runs r
JOIN automation_tasks t ON t.task_id = r.task_id;

CREATE TABLE automation_provider_observations (
    observation_id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL,
    occurrence INTEGER NOT NULL,
    provider_id TEXT NOT NULL,
    operation_id TEXT NOT NULL,
    observation TEXT NOT NULL CHECK (
        observation IN ('accepted', 'succeeded', 'failed', 'indeterminate', 'not_admitted')
    ),
    payload_digest TEXT NOT NULL,
    observed_at_ms INTEGER NOT NULL,
    detail TEXT,
    FOREIGN KEY (task_id, occurrence)
        REFERENCES automation_occurrences(task_id, occurrence),
    UNIQUE (
        task_id, occurrence, provider_id, operation_id,
        observation, payload_digest
    )
);

CREATE INDEX automation_provider_observation_lookup
    ON automation_provider_observations(task_id, occurrence, observed_at_ms, observation_id);


-- Durable TaskFlow step intent/outbox is now part of the default store schema.
-- This table is append-only evidence; provider authority remains a separate
-- final-use verification boundary.
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
