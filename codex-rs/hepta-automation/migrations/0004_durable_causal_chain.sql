-- Production-path durable automation occurrence lifecycle and TaskFlow step outbox.
--
-- v1-v3 deliberately stopped durable automation at Core queue admission and kept
-- TaskFlow step receipts behind qualification-only lazy schema creation.  This
-- migration preserves those tables and APIs while adding the missing owner-local
-- causal chain.  Queue admission remains an intermediate observation; an
-- occurrence is terminal only after an explicit terminal observation or
-- reconciliation.

CREATE TABLE automation_schedule_metadata (
    task_id TEXT PRIMARY KEY REFERENCES automation_tasks(task_id),
    owner_agent_id TEXT NOT NULL,
    revision INTEGER NOT NULL CHECK (revision > 0),
    missed_run_policy TEXT NOT NULL CHECK (
        missed_run_policy IN ('skip', 'coalesce', 'catch_up')
    ),
    max_catch_up_occurrences INTEGER NOT NULL CHECK (
        max_catch_up_occurrences >= 0 AND max_catch_up_occurrences <= 1024
    ),
    catch_up_remaining INTEGER NOT NULL CHECK (
        catch_up_remaining >= 0 AND catch_up_remaining <= 1024
    ),
    overlap_policy TEXT NOT NULL CHECK (
        overlap_policy IN ('forbid', 'allow')
    ),
    created_at_ms INTEGER NOT NULL CHECK (created_at_ms >= 0),
    updated_at_ms INTEGER NOT NULL CHECK (updated_at_ms >= 0),
    UNIQUE (owner_agent_id, task_id)
);

INSERT INTO automation_schedule_metadata (
    task_id, owner_agent_id, revision, missed_run_policy,
    max_catch_up_occurrences, catch_up_remaining, overlap_policy,
    created_at_ms, updated_at_ms
)
SELECT task_id, owner_agent_id, 1, 'skip', 32, 0, 'forbid',
       created_at_ms, updated_at_ms
FROM automation_tasks;

CREATE TRIGGER automation_schedule_metadata_identity_no_update
BEFORE UPDATE OF task_id, owner_agent_id ON automation_schedule_metadata
BEGIN
    SELECT RAISE(ABORT, 'automation schedule identity is immutable');
END;

CREATE TABLE automation_occurrence_lifecycle (
    task_id TEXT NOT NULL,
    occurrence INTEGER NOT NULL CHECK (occurrence > 0),
    occurrence_id TEXT NOT NULL UNIQUE,
    owner_agent_id TEXT NOT NULL,
    schedule_revision INTEGER NOT NULL CHECK (schedule_revision > 0),
    scheduled_for_ms INTEGER NOT NULL CHECK (scheduled_for_ms >= 0),
    client_user_message_id TEXT NOT NULL UNIQUE,
    state TEXT NOT NULL CHECK (
        state IN ('claimed', 'admitted', 'running', 'succeeded', 'failed',
                  'cancelled', 'indeterminate')
    ),
    overlap_policy TEXT NOT NULL CHECK (overlap_policy IN ('forbid', 'allow')),
    claim_generation INTEGER NOT NULL CHECK (claim_generation > 0),
    claim_token TEXT NOT NULL CHECK (length(claim_token) BETWEEN 1 AND 256),
    taskflow_run_id TEXT NOT NULL UNIQUE,
    queued_submission_id TEXT,
    provider_payload_sha256 TEXT CHECK (
        provider_payload_sha256 IS NULL OR
        (length(provider_payload_sha256) = 64 AND
         provider_payload_sha256 NOT GLOB '*[^0-9a-f]*')
    ),
    turn_id TEXT,
    terminal_receipt_digest TEXT CHECK (
        terminal_receipt_digest IS NULL OR
        (length(terminal_receipt_digest) = 64 AND
         terminal_receipt_digest NOT GLOB '*[^0-9a-f]*')
    ),
    recovery_phase TEXT NOT NULL CHECK (
        recovery_phase IN ('awaiting_admission', 'awaiting_turn',
                           'awaiting_terminal', 'reconciliation_required', 'terminal')
    ),
    created_at_ms INTEGER NOT NULL CHECK (created_at_ms >= 0),
    updated_at_ms INTEGER NOT NULL CHECK (updated_at_ms >= 0),
    terminal_at_ms INTEGER CHECK (terminal_at_ms IS NULL OR terminal_at_ms >= 0),
    PRIMARY KEY (task_id, occurrence),
    FOREIGN KEY (task_id, occurrence)
        REFERENCES automation_runs(task_id, occurrence),
    CHECK (
        (state IN ('succeeded', 'failed', 'cancelled')
            AND recovery_phase = 'terminal'
            AND terminal_receipt_digest IS NOT NULL
            AND terminal_at_ms IS NOT NULL)
        OR
        (state = 'indeterminate'
            AND recovery_phase = 'reconciliation_required'
            AND terminal_at_ms IS NULL)
        OR
        (state IN ('claimed', 'admitted', 'running')
            AND recovery_phase != 'terminal'
            AND terminal_at_ms IS NULL)
    )
);

CREATE INDEX automation_occurrence_recovery_idx
    ON automation_occurrence_lifecycle(
        owner_agent_id, recovery_phase, updated_at_ms, task_id, occurrence
    );

CREATE INDEX automation_occurrence_task_state_idx
    ON automation_occurrence_lifecycle(task_id, state, occurrence);

CREATE TRIGGER automation_occurrence_identity_no_update
BEFORE UPDATE OF task_id, occurrence, occurrence_id, owner_agent_id,
                 schedule_revision, scheduled_for_ms, client_user_message_id,
                 taskflow_run_id
ON automation_occurrence_lifecycle
BEGIN
    SELECT RAISE(ABORT, 'automation occurrence identity is immutable');
END;

CREATE TABLE automation_occurrence_events (
    task_id TEXT NOT NULL,
    occurrence INTEGER NOT NULL CHECK (occurrence > 0),
    event_seq INTEGER NOT NULL CHECK (event_seq > 0),
    event_kind TEXT NOT NULL CHECK (
        event_kind IN ('claimed', 'reclaimed', 'admitted', 'turn_persisted',
                       'indeterminate', 'succeeded', 'failed', 'cancelled')
    ),
    command_id TEXT NOT NULL,
    command_digest TEXT NOT NULL CHECK (
        length(command_digest) = 64 AND command_digest NOT GLOB '*[^0-9a-f]*'
    ),
    state TEXT NOT NULL CHECK (
        state IN ('claimed', 'admitted', 'running', 'succeeded', 'failed',
                  'cancelled', 'indeterminate')
    ),
    receipt_digest TEXT CHECK (
        receipt_digest IS NULL OR
        (length(receipt_digest) = 64 AND receipt_digest NOT GLOB '*[^0-9a-f]*')
    ),
    previous_event_digest TEXT NOT NULL CHECK (
        length(previous_event_digest) = 64 AND
        previous_event_digest NOT GLOB '*[^0-9a-f]*'
    ),
    event_digest TEXT NOT NULL CHECK (
        length(event_digest) = 64 AND event_digest NOT GLOB '*[^0-9a-f]*'
    ),
    recorded_at_ms INTEGER NOT NULL CHECK (recorded_at_ms >= 0),
    PRIMARY KEY (task_id, occurrence, event_seq),
    UNIQUE (task_id, occurrence, command_id),
    FOREIGN KEY (task_id, occurrence)
        REFERENCES automation_occurrence_lifecycle(task_id, occurrence)
);

CREATE TRIGGER automation_occurrence_events_no_update
BEFORE UPDATE ON automation_occurrence_events
BEGIN
    SELECT RAISE(ABORT, 'automation occurrence events are append-only');
END;

CREATE TRIGGER automation_occurrence_events_no_delete
BEFORE DELETE ON automation_occurrence_events
BEGIN
    SELECT RAISE(ABORT, 'automation occurrence events are append-only');
END;

-- Promote the already-qualified TaskFlow step intent/receipt chain into the
-- normal durable schema.  IF NOT EXISTS preserves stores where the opt-in
-- qualification API created the exact table before this migration.
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

-- Canonical read-domain names.  Existing owner tables remain the storage
-- compatibility surface; these views expose the schedule/occurrence facts as
-- the domain contract names used by the architecture registries.
CREATE VIEW automation_schedule AS
SELECT t.task_id,
       t.owner_agent_id,
       m.revision,
       t.thread_id,
       t.prompt,
       t.schedule_kind,
       t.interval_ms,
       t.state,
       t.next_run_at_ms,
       t.next_occurrence,
       m.missed_run_policy,
       m.max_catch_up_occurrences,
       m.overlap_policy,
       t.created_at_ms,
       t.updated_at_ms
FROM automation_tasks t
JOIN automation_schedule_metadata m ON m.task_id = t.task_id;

CREATE VIEW automation_occurrence AS
SELECT o.task_id,
       o.occurrence,
       o.occurrence_id,
       o.owner_agent_id,
       o.schedule_revision,
       o.scheduled_for_ms,
       o.client_user_message_id,
       o.state,
       o.overlap_policy,
       o.claim_generation,
       o.taskflow_run_id,
       o.queued_submission_id,
       o.provider_payload_sha256,
       o.turn_id,
       o.terminal_receipt_digest,
       o.recovery_phase,
       o.created_at_ms,
       o.updated_at_ms,
       o.terminal_at_ms
FROM automation_occurrence_lifecycle o;

DROP TRIGGER automation_meta_no_update;
UPDATE automation_meta SET schema_version = 4 WHERE singleton = 1;
CREATE TRIGGER automation_meta_no_update
BEFORE UPDATE ON automation_meta
BEGIN
    SELECT RAISE(ABORT, 'automation owner metadata is immutable');
END;
