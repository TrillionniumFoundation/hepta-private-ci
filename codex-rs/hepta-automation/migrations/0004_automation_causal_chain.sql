-- Durable automation occurrence / TaskFlow causal-chain bridge.
--
-- Queue admission remains dispatch evidence only.  Execution completion is
-- tracked independently and may become terminal only from the bound TaskFlow
-- run.  Historical submitted rows are conservatively migrated to
-- indeterminate because queue acceptance never proved effect completion.

ALTER TABLE automation_tasks
    ADD COLUMN schedule_revision INTEGER NOT NULL DEFAULT 1
        CHECK (schedule_revision > 0);
ALTER TABLE automation_tasks
    ADD COLUMN missed_run_policy TEXT NOT NULL DEFAULT 'skip'
        CHECK (missed_run_policy IN ('skip', 'bounded_catch_up'));
ALTER TABLE automation_tasks
    ADD COLUMN max_catch_up_occurrences INTEGER NOT NULL DEFAULT 1
        CHECK (max_catch_up_occurrences BETWEEN 1 AND 1024);
ALTER TABLE automation_tasks
    ADD COLUMN overlap_policy TEXT NOT NULL DEFAULT 'forbid'
        CHECK (overlap_policy IN ('forbid', 'allow'));

ALTER TABLE automation_runs
    ADD COLUMN occurrence_id TEXT NOT NULL DEFAULT 'migration-pending';
ALTER TABLE automation_runs
    ADD COLUMN schedule_revision INTEGER NOT NULL DEFAULT 1
        CHECK (schedule_revision > 0);
ALTER TABLE automation_runs
    ADD COLUMN execution_state TEXT NOT NULL DEFAULT 'materialized'
        CHECK (execution_state IN (
            'materialized', 'taskflow_bound', 'running', 'indeterminate',
            'succeeded', 'failed', 'cancelled'
        ));
ALTER TABLE automation_runs
    ADD COLUMN terminal_at_ms INTEGER CHECK (terminal_at_ms IS NULL OR terminal_at_ms >= 0);

UPDATE automation_runs
SET occurrence_id =
        'hepta.automation.occurrence.v1:' || task_id || ':' ||
        schedule_revision || ':' || scheduled_for_ms,
    execution_state = CASE
        WHEN state = 'submitted' THEN 'indeterminate'
        WHEN state = 'cancelled' THEN 'cancelled'
        ELSE 'materialized'
    END;

-- v3 marked a one-shot task completed as soon as App Server accepted the
-- queue request. Preserve no-rerun behavior (next_run_at_ms is already NULL)
-- but remove that unproved terminal claim. The indeterminate occurrence must
-- be explicitly reconciled through TaskFlow before completion is restored.
UPDATE automation_tasks
SET state = 'enabled'
WHERE schedule_kind = 'once'
  AND state = 'completed'
  AND EXISTS (
      SELECT 1 FROM automation_runs r
      WHERE r.task_id = automation_tasks.task_id
        AND r.execution_state = 'indeterminate'
  );

CREATE UNIQUE INDEX automation_runs_occurrence_id_unique
    ON automation_runs(occurrence_id);

CREATE TRIGGER automation_runs_occurrence_id_required
BEFORE INSERT ON automation_runs
WHEN NEW.occurrence_id NOT GLOB 'hepta.automation.occurrence.v1:*'
BEGIN
    SELECT RAISE(ABORT, 'automation occurrence id is required');
END;

CREATE TABLE automation_occurrence_taskflow (
    owner_agent_id TEXT NOT NULL,
    occurrence_id TEXT NOT NULL,
    task_id TEXT NOT NULL,
    occurrence INTEGER NOT NULL CHECK (occurrence > 0),
    taskflow_run_id TEXT NOT NULL,
    bound_at_ms INTEGER NOT NULL CHECK (bound_at_ms >= 0),
    PRIMARY KEY (owner_agent_id, occurrence_id),
    UNIQUE (owner_agent_id, taskflow_run_id),
    UNIQUE (task_id, occurrence),
    FOREIGN KEY (task_id, occurrence)
        REFERENCES automation_runs(task_id, occurrence),
    FOREIGN KEY (owner_agent_id, taskflow_run_id)
        REFERENCES taskflow_runs(owner_agent_id, run_id)
);

CREATE TRIGGER automation_occurrence_taskflow_no_update
BEFORE UPDATE ON automation_occurrence_taskflow
BEGIN
    SELECT RAISE(ABORT, 'automation occurrence TaskFlow binding is immutable');
END;

CREATE TRIGGER automation_occurrence_taskflow_no_delete
BEFORE DELETE ON automation_occurrence_taskflow
BEGIN
    SELECT RAISE(ABORT, 'automation occurrence TaskFlow binding is immutable');
END;

CREATE INDEX automation_occurrence_taskflow_lookup
    ON automation_occurrence_taskflow(owner_agent_id, task_id, occurrence);

-- Promote the existing durable step outbox into the default schema.  This is
-- storage availability only: it grants no provider, scheduler, or authority
-- capability.
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
