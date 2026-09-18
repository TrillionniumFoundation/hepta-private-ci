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

DROP TRIGGER automation_meta_no_update;
UPDATE automation_meta SET schema_version = 4 WHERE singleton = 1;
CREATE TRIGGER automation_meta_no_update
BEFORE UPDATE ON automation_meta
BEGIN
    SELECT RAISE(ABORT, 'automation owner metadata is immutable');
END;
