-- Production durable causal chain for automation.taskflow.
--
-- Existing automation_runs remains the scheduler lease/admission journal.
-- automation_occurrences is the semantic occurrence ledger: identity is bound
-- to schedule revision + scheduled instant and does not become terminal on
-- queue admission.

ALTER TABLE automation_tasks
    ADD COLUMN schedule_revision INTEGER NOT NULL DEFAULT 1 CHECK (schedule_revision > 0);
ALTER TABLE automation_tasks
    ADD COLUMN overlap_policy TEXT NOT NULL DEFAULT 'forbid'
        CHECK (overlap_policy IN ('forbid', 'queue', 'allow'));
ALTER TABLE automation_tasks
    ADD COLUMN missed_run_policy TEXT NOT NULL DEFAULT 'coalesce_latest'
        CHECK (missed_run_policy IN ('skip', 'coalesce_latest', 'catch_up_bounded'));
ALTER TABLE automation_tasks
    ADD COLUMN max_catch_up INTEGER NOT NULL DEFAULT 1
        CHECK (max_catch_up > 0 AND max_catch_up <= 1024);

CREATE TABLE automation_occurrences (
    owner_agent_id TEXT NOT NULL,
    occurrence_id TEXT NOT NULL,
    task_id TEXT NOT NULL REFERENCES automation_tasks(task_id),
    schedule_revision INTEGER NOT NULL CHECK (schedule_revision > 0),
    ordinal INTEGER NOT NULL CHECK (ordinal > 0),
    scheduled_for_ms INTEGER NOT NULL CHECK (scheduled_for_ms >= 0),
    client_user_message_id TEXT NOT NULL,
    state TEXT NOT NULL CHECK (
        state IN (
            'materialized', 'queue_admitted', 'taskflow_bound', 'running',
            'indeterminate', 'succeeded', 'failed', 'cancelled'
        )
    ),
    queued_submission_id TEXT,
    taskflow_run_id TEXT,
    provider_observation_digest TEXT CHECK (
        provider_observation_digest IS NULL OR
        (length(provider_observation_digest) = 64
         AND provider_observation_digest NOT GLOB '*[^0-9a-f]*')
    ),
    terminal_reason TEXT,
    materialized_at_ms INTEGER NOT NULL CHECK (materialized_at_ms >= 0),
    updated_at_ms INTEGER NOT NULL CHECK (updated_at_ms >= 0),
    terminal_at_ms INTEGER,
    PRIMARY KEY (owner_agent_id, occurrence_id),
    UNIQUE (owner_agent_id, task_id, schedule_revision, scheduled_for_ms),
    UNIQUE (owner_agent_id, task_id, ordinal),
    UNIQUE (owner_agent_id, client_user_message_id),
    CHECK (
        (state IN ('succeeded', 'failed', 'cancelled') AND terminal_at_ms IS NOT NULL)
        OR (state NOT IN ('succeeded', 'failed', 'cancelled') AND terminal_at_ms IS NULL)
    )
);

CREATE INDEX automation_occurrences_state_idx
    ON automation_occurrences(owner_agent_id, state, scheduled_for_ms, occurrence_id);
CREATE INDEX automation_occurrences_task_idx
    ON automation_occurrences(owner_agent_id, task_id, ordinal);

CREATE TABLE automation_provider_observations (
    owner_agent_id TEXT NOT NULL,
    occurrence_id TEXT NOT NULL,
    run_id TEXT NOT NULL,
    step_id TEXT NOT NULL,
    attempt INTEGER NOT NULL CHECK (attempt > 0),
    receipt_digest TEXT NOT NULL CHECK (
        length(receipt_digest) = 64 AND receipt_digest NOT GLOB '*[^0-9a-f]*'
    ),
    observation TEXT NOT NULL CHECK (
        observation IN ('succeeded', 'failed', 'indeterminate')
    ),
    observed_at_ms INTEGER NOT NULL CHECK (observed_at_ms >= 0),
    PRIMARY KEY (owner_agent_id, occurrence_id, run_id, step_id, attempt, receipt_digest),
    FOREIGN KEY (owner_agent_id, occurrence_id)
        REFERENCES automation_occurrences(owner_agent_id, occurrence_id),
    FOREIGN KEY (owner_agent_id, run_id)
        REFERENCES taskflow_runs(owner_agent_id, run_id)
);

CREATE INDEX automation_provider_observations_lookup
    ON automation_provider_observations(owner_agent_id, occurrence_id, observed_at_ms);

-- Promote the existing durable step intent/receipt chain into the default
-- schema. The runtime API still grants no provider authority by itself.
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
        length(previous_event_digest) = 64 AND previous_event_digest NOT GLOB '*[^0-9a-f]*'
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
