-- Durable automation causal-chain foundation.
--
-- v4 separates scheduler lease/queue bookkeeping (automation_runs) from the
-- canonical occurrence lifecycle.  Queue admission is explicitly non-terminal.
-- Schedule revisions are immutable and every occurrence is bound to exactly one
-- revision plus one canonical scheduled instant.

CREATE TABLE automation_schedule_revisions (
    task_id TEXT NOT NULL,
    revision INTEGER NOT NULL CHECK (revision > 0),
    owner_agent_id TEXT NOT NULL,
    schedule_kind TEXT NOT NULL CHECK (schedule_kind IN ('once', 'fixed_interval')),
    interval_ms INTEGER,
    timezone TEXT NOT NULL,
    overlap_policy TEXT NOT NULL CHECK (overlap_policy IN ('forbid')),
    missed_run_policy TEXT NOT NULL CHECK (
        missed_run_policy IN ('skip', 'coalesce_latest')
    ),
    registered_at_ms INTEGER NOT NULL CHECK (registered_at_ms >= 0),
    PRIMARY KEY (task_id, revision),
    FOREIGN KEY (task_id) REFERENCES automation_tasks(task_id),
    CHECK (
        (schedule_kind = 'once' AND interval_ms IS NULL)
        OR
        (schedule_kind = 'fixed_interval' AND interval_ms IS NOT NULL AND interval_ms > 0)
    ),
    CHECK (length(timezone) BETWEEN 1 AND 128)
);

CREATE TRIGGER automation_schedule_revisions_no_update
BEFORE UPDATE ON automation_schedule_revisions
BEGIN
    SELECT RAISE(ABORT, 'automation schedule revisions are immutable');
END;

CREATE TRIGGER automation_schedule_revisions_no_delete
BEFORE DELETE ON automation_schedule_revisions
BEGIN
    SELECT RAISE(ABORT, 'automation schedule revisions are immutable');
END;

CREATE INDEX automation_schedule_revision_owner_idx
    ON automation_schedule_revisions(owner_agent_id, task_id, revision);

-- Existing schedules predate explicit revision/policy metadata.  They become
-- revision 1 with the only timezone semantics they actually implemented (UTC),
-- overlap forbidden, and bounded coalescing for missed fixed-interval slots.
INSERT INTO automation_schedule_revisions (
    task_id, revision, owner_agent_id, schedule_kind, interval_ms, timezone,
    overlap_policy, missed_run_policy, registered_at_ms
)
SELECT task_id, 1, owner_agent_id, schedule_kind, interval_ms, 'UTC',
       'forbid', 'coalesce_latest', created_at_ms
FROM automation_tasks;

CREATE TABLE automation_occurrences (
    occurrence_id TEXT PRIMARY KEY,
    owner_agent_id TEXT NOT NULL,
    task_id TEXT NOT NULL,
    occurrence INTEGER NOT NULL CHECK (occurrence > 0),
    schedule_revision INTEGER NOT NULL CHECK (schedule_revision > 0),
    scheduled_for_ms INTEGER NOT NULL CHECK (scheduled_for_ms >= 0),
    client_user_message_id TEXT NOT NULL UNIQUE,
    state TEXT NOT NULL CHECK (
        state IN (
            'materialized', 'dispatch_uncertain', 'queue_admitted',
            'taskflow_bound', 'running', 'indeterminate',
            'succeeded', 'failed', 'cancelled'
        )
    ),
    queued_submission_id TEXT UNIQUE,
    turn_id TEXT,
    taskflow_run_id TEXT,
    terminal_reason TEXT,
    created_at_ms INTEGER NOT NULL CHECK (created_at_ms >= 0),
    updated_at_ms INTEGER NOT NULL CHECK (updated_at_ms >= 0),
    UNIQUE (task_id, occurrence),
    UNIQUE (task_id, schedule_revision, scheduled_for_ms),
    FOREIGN KEY (task_id, occurrence)
        REFERENCES automation_runs(task_id, occurrence),
    FOREIGN KEY (task_id, schedule_revision)
        REFERENCES automation_schedule_revisions(task_id, revision),
    FOREIGN KEY (owner_agent_id, taskflow_run_id)
        REFERENCES taskflow_runs(owner_agent_id, run_id),
    CHECK (
        (state IN ('succeeded', 'failed', 'cancelled') AND terminal_reason IS NOT NULL)
        OR (state NOT IN ('succeeded', 'failed', 'cancelled') AND terminal_reason IS NULL)
    )
);

CREATE INDEX automation_occurrence_state_idx
    ON automation_occurrences(owner_agent_id, state, updated_at_ms, occurrence_id);

CREATE INDEX automation_occurrence_task_idx
    ON automation_occurrences(task_id, occurrence, schedule_revision);

-- Preserve legacy truth: a submitted automation_run proves queue admission,
-- not TaskFlow/effect completion.
INSERT INTO automation_occurrences (
    occurrence_id, owner_agent_id, task_id, occurrence, schedule_revision,
    scheduled_for_ms, client_user_message_id, state, queued_submission_id,
    created_at_ms, updated_at_ms
)
SELECT
    'hepta.automation.occurrence.v1:' || r.task_id || ':1:' || r.scheduled_for_ms,
    t.owner_agent_id,
    r.task_id,
    r.occurrence,
    1,
    r.scheduled_for_ms,
    r.client_user_message_id,
    CASE
        WHEN o.outcome = 'uncertain' THEN 'dispatch_uncertain'
        WHEN r.state = 'submitted' THEN 'queue_admitted'
        WHEN r.state = 'cancelled' THEN 'cancelled'
        ELSE 'materialized'
    END,
    r.queued_submission_id,
    CASE WHEN r.state = 'cancelled' THEN 'legacy_cancelled_before_terminal_tracking' ELSE NULL END,
    t.created_at_ms,
    COALESCE(r.submitted_at_ms, o.observed_at_ms, t.updated_at_ms)
FROM automation_runs r
JOIN automation_tasks t ON t.task_id = r.task_id
LEFT JOIN automation_dispatch_outcomes o
  ON o.task_id = r.task_id AND o.occurrence = r.occurrence;

-- Promote the already-implemented durable TaskFlow step outbox into the normal
-- migrated schema.  Its API still grants no provider authority by itself.
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

CREATE INDEX IF NOT EXISTS taskflow_step_outbox_run_lookup
    ON taskflow_step_outbox(owner_agent_id, run_id, step_id, attempt, event_seq);

DROP TRIGGER automation_meta_no_update;
UPDATE automation_meta SET schema_version = 4 WHERE singleton = 1;
CREATE TRIGGER automation_meta_no_update
BEFORE UPDATE ON automation_meta
BEGIN
    SELECT RAISE(ABORT, 'automation owner metadata is immutable');
END;
