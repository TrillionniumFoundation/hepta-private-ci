-- A versioned profile in the existing per-Agent owner, not new V1 semantics.
CREATE TABLE circuit_v2_definitions (
    owner_agent_id TEXT NOT NULL,
    circuit_id TEXT NOT NULL,
    version INTEGER NOT NULL CHECK (version > 0),
    definition_digest TEXT NOT NULL CHECK (length(definition_digest) = 64),
    definition_json TEXT NOT NULL CHECK (length(definition_json) <= 262144),
    PRIMARY KEY (owner_agent_id, circuit_id, version),
    UNIQUE (owner_agent_id, definition_digest)
);
CREATE TABLE circuit_v2_runs (
    owner_agent_id TEXT NOT NULL,
    run_id TEXT NOT NULL,
    definition_digest TEXT NOT NULL,
    revision INTEGER NOT NULL CHECK (revision >= 0),
    state_json TEXT NOT NULL CHECK (length(state_json) <= 8388608),
    state_digest TEXT NOT NULL CHECK (length(state_digest) = 64),
    last_event_digest TEXT NOT NULL CHECK (length(last_event_digest) = 64),
    PRIMARY KEY (owner_agent_id, run_id),
    FOREIGN KEY (owner_agent_id, definition_digest)
        REFERENCES circuit_v2_definitions(owner_agent_id, definition_digest)
);
CREATE TABLE circuit_v2_events (
    owner_agent_id TEXT NOT NULL,
    run_id TEXT NOT NULL,
    seq INTEGER NOT NULL CHECK (seq >= 0),
    command_id TEXT NOT NULL,
    command_digest TEXT NOT NULL CHECK (length(command_digest) = 64),
    event_json TEXT NOT NULL CHECK (length(event_json) <= 131072),
    previous_digest TEXT NOT NULL CHECK (length(previous_digest) = 64),
    state_digest TEXT NOT NULL CHECK (length(state_digest) = 64),
    event_digest TEXT NOT NULL CHECK (length(event_digest) = 64),
    PRIMARY KEY (owner_agent_id, run_id, seq),
    UNIQUE (owner_agent_id, run_id, command_id),
    FOREIGN KEY (owner_agent_id, run_id) REFERENCES circuit_v2_runs(owner_agent_id, run_id)
);
CREATE TRIGGER circuit_v2_definition_owner BEFORE INSERT ON circuit_v2_definitions
WHEN NEW.owner_agent_id IS NOT (SELECT owner_agent_id FROM automation_meta WHERE singleton = 1)
BEGIN SELECT RAISE(ABORT, 'circuit owner mismatch'); END;
CREATE TRIGGER circuit_v2_run_owner BEFORE INSERT ON circuit_v2_runs
WHEN NEW.owner_agent_id IS NOT (SELECT owner_agent_id FROM automation_meta WHERE singleton = 1)
BEGIN SELECT RAISE(ABORT, 'circuit owner mismatch'); END;
CREATE TRIGGER circuit_v2_run_identity BEFORE UPDATE OF owner_agent_id, run_id, definition_digest ON circuit_v2_runs
WHEN NEW.owner_agent_id != OLD.owner_agent_id OR NEW.run_id != OLD.run_id OR NEW.definition_digest != OLD.definition_digest
BEGIN SELECT RAISE(ABORT, 'circuit run identity is immutable'); END;
CREATE TRIGGER circuit_v2_definition_no_update BEFORE UPDATE ON circuit_v2_definitions
BEGIN SELECT RAISE(ABORT, 'circuit definitions are immutable'); END;
CREATE TRIGGER circuit_v2_definition_no_delete BEFORE DELETE ON circuit_v2_definitions
BEGIN SELECT RAISE(ABORT, 'circuit definitions are immutable'); END;
CREATE TRIGGER circuit_v2_event_no_update BEFORE UPDATE ON circuit_v2_events
BEGIN SELECT RAISE(ABORT, 'circuit events are immutable'); END;
CREATE TRIGGER circuit_v2_event_no_delete BEFORE DELETE ON circuit_v2_events
BEGIN SELECT RAISE(ABORT, 'circuit events are immutable'); END;
CREATE TRIGGER circuit_v2_run_no_delete BEFORE DELETE ON circuit_v2_runs
BEGIN SELECT RAISE(ABORT, 'circuit runs retain unresolved work and history'); END;
DROP TRIGGER automation_meta_no_update;
UPDATE automation_meta SET schema_version = 20 WHERE singleton = 1;
CREATE TRIGGER automation_meta_no_update BEFORE UPDATE ON automation_meta
BEGIN SELECT RAISE(ABORT, 'automation owner metadata is immutable'); END;
