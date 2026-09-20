-- Agent-local qualification-only TaskFlow definition/run ledger.
--
-- This migration deliberately lives beside the existing per-Agent timer
-- store.  It adds no scheduler or provider authority: definitions and run
-- transitions are immutable evidence, while the existing automation scheduler
-- remains the sole wakeup owner.

CREATE TABLE taskflow_definitions (
    owner_agent_id TEXT NOT NULL,
    workflow_id TEXT NOT NULL,
    version INTEGER NOT NULL CHECK (version > 0),
    definition_digest TEXT NOT NULL CHECK (
        length(definition_digest) = 64 AND
        definition_digest NOT GLOB '*[^0-9a-f]*'
    ),
    definition_json TEXT NOT NULL,
    registered_generation INTEGER NOT NULL CHECK (registered_generation > 0),
    registered_at_ms INTEGER NOT NULL CHECK (registered_at_ms >= 0),
    PRIMARY KEY (owner_agent_id, workflow_id, version),
    UNIQUE (owner_agent_id, workflow_id, definition_digest)
);

CREATE TRIGGER taskflow_definitions_no_update
BEFORE UPDATE ON taskflow_definitions
BEGIN
    SELECT RAISE(ABORT, 'TaskFlow definitions are immutable');
END;

CREATE TRIGGER taskflow_definitions_no_delete
BEFORE DELETE ON taskflow_definitions
BEGIN
    SELECT RAISE(ABORT, 'TaskFlow definitions are immutable');
END;

CREATE INDEX taskflow_definitions_digest_lookup
    ON taskflow_definitions(owner_agent_id, definition_digest);

CREATE TABLE taskflow_runs (
    owner_agent_id TEXT NOT NULL,
    run_id TEXT NOT NULL,
    workflow_id TEXT NOT NULL,
    workflow_version INTEGER NOT NULL CHECK (workflow_version > 0),
    definition_digest TEXT NOT NULL CHECK (
        length(definition_digest) = 64 AND
        definition_digest NOT GLOB '*[^0-9a-f]*'
    ),
    thread_id TEXT NOT NULL,
    state TEXT NOT NULL CHECK (
        state IN ('queued', 'running', 'waiting', 'retry_backoff',
                  'succeeded', 'failed', 'cancelled', 'indeterminate')
    ),
    revision INTEGER NOT NULL CHECK (revision >= 0),
    current_node TEXT NOT NULL,
    state_digest TEXT NOT NULL CHECK (
        length(state_digest) = 64 AND state_digest NOT GLOB '*[^0-9a-f]*'
    ),
    owner_id TEXT,
    owner_epoch INTEGER,
    generation INTEGER,
    fencing_token TEXT,
    lease_expires_at_ms INTEGER,
    cancel_requested INTEGER NOT NULL CHECK (cancel_requested IN (0, 1)),
    wait_token TEXT,
    retry_at_ms INTEGER,
    terminal_reason TEXT,
    created_at_ms INTEGER NOT NULL CHECK (created_at_ms >= 0),
    updated_at_ms INTEGER NOT NULL CHECK (updated_at_ms >= 0),
    PRIMARY KEY (owner_agent_id, run_id),
    UNIQUE (owner_agent_id, run_id, definition_digest),
    FOREIGN KEY (owner_agent_id, workflow_id, workflow_version)
        REFERENCES taskflow_definitions(owner_agent_id, workflow_id, version),
    CHECK (
        (owner_id IS NULL AND owner_epoch IS NULL AND generation IS NULL
         AND fencing_token IS NULL AND lease_expires_at_ms IS NULL)
        OR
        (owner_id IS NOT NULL AND owner_epoch IS NOT NULL AND owner_epoch > 0
         AND generation IS NOT NULL AND generation > 0
         AND fencing_token IS NOT NULL AND length(fencing_token) BETWEEN 1 AND 256
         AND lease_expires_at_ms IS NOT NULL AND lease_expires_at_ms >= 0)
    )
);

CREATE INDEX taskflow_runs_state_lookup
    ON taskflow_runs(owner_agent_id, state, updated_at_ms, run_id);

CREATE TABLE taskflow_events (
    owner_agent_id TEXT NOT NULL,
    run_id TEXT NOT NULL,
    event_seq INTEGER NOT NULL CHECK (event_seq > 0),
    command_id TEXT NOT NULL,
    command_digest TEXT NOT NULL CHECK (
        length(command_digest) = 64 AND command_digest NOT GLOB '*[^0-9a-f]*'
    ),
    transition TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    revision INTEGER NOT NULL CHECK (revision > 0),
    state_digest TEXT NOT NULL CHECK (
        length(state_digest) = 64 AND state_digest NOT GLOB '*[^0-9a-f]*'
    ),
    previous_event_digest TEXT NOT NULL CHECK (
        length(previous_event_digest) = 64 AND previous_event_digest NOT GLOB '*[^0-9a-f]*'
    ),
    event_digest TEXT NOT NULL CHECK (
        length(event_digest) = 64 AND event_digest NOT GLOB '*[^0-9a-f]*'
    ),
    owner_id TEXT,
    owner_epoch INTEGER,
    generation INTEGER,
    fencing_token TEXT,
    recorded_at_ms INTEGER NOT NULL CHECK (recorded_at_ms >= 0),
    PRIMARY KEY (owner_agent_id, run_id, event_seq),
    UNIQUE (owner_agent_id, run_id, command_id),
    FOREIGN KEY (owner_agent_id, run_id)
        REFERENCES taskflow_runs(owner_agent_id, run_id)
);

CREATE TRIGGER taskflow_events_no_update
BEFORE UPDATE ON taskflow_events
BEGIN
    SELECT RAISE(ABORT, 'TaskFlow events are immutable');
END;

CREATE TRIGGER taskflow_events_no_delete
BEFORE DELETE ON taskflow_events
BEGIN
    SELECT RAISE(ABORT, 'TaskFlow events are immutable');
END;

CREATE INDEX taskflow_events_command_lookup
    ON taskflow_events(owner_agent_id, command_id);

CREATE INDEX taskflow_events_run_lookup
    ON taskflow_events(owner_agent_id, run_id, event_seq);

DROP TRIGGER automation_meta_no_update;
UPDATE automation_meta SET schema_version = 3 WHERE singleton = 1;
CREATE TRIGGER automation_meta_no_update
BEFORE UPDATE ON automation_meta
BEGIN
    SELECT RAISE(ABORT, 'automation owner metadata is immutable');
END;
