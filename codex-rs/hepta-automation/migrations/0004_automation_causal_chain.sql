-- Durable automation causal-chain schema.
--
-- This migration does not create another scheduler or workflow engine. It
-- extends the existing scheduler rows with immutable schedule/occurrence
-- identity, explicit recurrence policy, provider observations and the existing
-- TaskFlow step outbox so queue admission can no longer stand in for terminal
-- automation completion.

ALTER TABLE automation_tasks
    ADD COLUMN schedule_revision INTEGER NOT NULL DEFAULT 1
    CHECK (schedule_revision > 0);

ALTER TABLE automation_tasks
    ADD COLUMN overlap_policy TEXT NOT NULL DEFAULT 'forbid'
    CHECK (overlap_policy IN ('forbid', 'allow'));

ALTER TABLE automation_tasks
    ADD COLUMN missed_run_policy TEXT NOT NULL DEFAULT 'bounded_catch_up'
    CHECK (missed_run_policy IN ('skip', 'coalesce', 'bounded_catch_up'));

ALTER TABLE automation_tasks
    ADD COLUMN missed_run_limit INTEGER DEFAULT 32
    CHECK (
        (missed_run_policy IN ('skip', 'coalesce') AND missed_run_limit IS NULL)
        OR
        (missed_run_policy = 'bounded_catch_up'
         AND missed_run_limit BETWEEN 1 AND 1024)
    );

ALTER TABLE automation_runs
    ADD COLUMN occurrence_id TEXT NOT NULL DEFAULT ''
    CHECK (
        occurrence_id = ''
        OR (length(occurrence_id) = 64 AND occurrence_id NOT GLOB '*[^0-9a-f]*')
    );

ALTER TABLE automation_runs
    ADD COLUMN schedule_revision INTEGER NOT NULL DEFAULT 1
    CHECK (schedule_revision > 0);

ALTER TABLE automation_runs
    ADD COLUMN taskflow_run_id TEXT;

ALTER TABLE automation_runs
    ADD COLUMN provider_turn_id TEXT;

ALTER TABLE automation_runs
    ADD COLUMN terminal_state TEXT
    CHECK (terminal_state IS NULL OR terminal_state IN ('succeeded', 'failed', 'cancelled'));

ALTER TABLE automation_runs
    ADD COLUMN terminal_at_ms INTEGER
    CHECK (terminal_at_ms IS NULL OR terminal_at_ms >= 0);

CREATE UNIQUE INDEX automation_occurrence_identity_idx
    ON automation_runs(occurrence_id)
    WHERE occurrence_id != '';

CREATE INDEX automation_active_occurrence_idx
    ON automation_runs(task_id, terminal_state, scheduled_for_ms, occurrence);

-- Provider evidence is append-only. Queue admission, persistence as a turn and
-- terminal turn observation are deliberately separate facts.
CREATE TABLE automation_provider_observations (
    task_id TEXT NOT NULL,
    occurrence INTEGER NOT NULL,
    observation_seq INTEGER NOT NULL CHECK (observation_seq > 0),
    observation_kind TEXT NOT NULL CHECK (
        observation_kind IN (
            'queue_admitted',
            'turn_persisted',
            'turn_completed',
            'turn_failed',
            'turn_interrupted',
            'indeterminate',
            'reconciled_missing',
            'reconciled_cancelled'
        )
    ),
    queued_submission_id TEXT,
    turn_id TEXT,
    receipt_digest TEXT NOT NULL CHECK (
        length(receipt_digest) = 64 AND receipt_digest NOT GLOB '*[^0-9a-f]*'
    ),
    observed_at_ms INTEGER NOT NULL CHECK (observed_at_ms >= 0),
    PRIMARY KEY (task_id, occurrence, observation_seq),
    FOREIGN KEY (task_id, occurrence)
        REFERENCES automation_runs(task_id, occurrence)
);

CREATE TRIGGER automation_provider_observations_no_update
BEFORE UPDATE ON automation_provider_observations
BEGIN
    SELECT RAISE(ABORT, 'automation provider observations are immutable');
END;

CREATE TRIGGER automation_provider_observations_no_delete
BEFORE DELETE ON automation_provider_observations
BEGIN
    SELECT RAISE(ABORT, 'automation provider observations are immutable');
END;

CREATE INDEX automation_provider_observation_lookup
    ON automation_provider_observations(task_id, occurrence, observation_seq);

-- Promote the already-qualified TaskFlow step receipt chain into the normal
-- automation schema. The table still grants no authority by itself.
CREATE TABLE taskflow_step_outbox (
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

CREATE TRIGGER taskflow_step_outbox_no_update
BEFORE UPDATE ON taskflow_step_outbox
BEGIN
    SELECT RAISE(ABORT, 'TaskFlow step outbox is append-only');
END;

CREATE TRIGGER taskflow_step_outbox_no_delete
BEFORE DELETE ON taskflow_step_outbox
BEGIN
    SELECT RAISE(ABORT, 'TaskFlow step outbox is append-only');
END;

CREATE INDEX taskflow_step_outbox_lookup
    ON taskflow_step_outbox(owner_agent_id, run_id, step_id, attempt, event_seq);

DROP TRIGGER automation_meta_no_update;
UPDATE automation_meta SET schema_version = 4 WHERE singleton = 1;
CREATE TRIGGER automation_meta_no_update
BEFORE UPDATE ON automation_meta
BEGIN
    SELECT RAISE(ABORT, 'automation owner metadata is immutable');
END;
