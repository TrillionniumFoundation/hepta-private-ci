-- Fresh, private unit-test prepare/claim profile; NOT a product migration.
-- FK targets are the actual schema19 run UNIQUE3 and native step PK5.
CREATE TABLE qualification_retrieval_binding (
    singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
    format_version INTEGER NOT NULL CHECK (format_version = 1),
    stage TEXT NOT NULL CHECK (stage = 'prepare_claim_v1'),
    owner_agent_id TEXT NOT NULL,
    canonical_root TEXT NOT NULL,
    correlation_id TEXT NOT NULL,
    base_schema_version INTEGER NOT NULL CHECK (base_schema_version = 19),
    clock_origin_ms INTEGER NOT NULL CHECK (clock_origin_ms = 1000)
);
CREATE TRIGGER qualification_binding_no_update
BEFORE UPDATE ON qualification_retrieval_binding BEGIN
    SELECT RAISE(ABORT, 'qualification binding is immutable');
END;
CREATE TRIGGER qualification_binding_no_delete
BEFORE DELETE ON qualification_retrieval_binding BEGIN
    SELECT RAISE(ABORT, 'qualification binding is immutable');
END;

CREATE TABLE qualification_retrieval_choices (
    owner_agent_id TEXT NOT NULL,
    run_id TEXT NOT NULL,
    activation_id TEXT NOT NULL,
    definition_digest TEXT NOT NULL,
    command_id TEXT NOT NULL,
    command_digest TEXT NOT NULL,
    command_bytes BLOB NOT NULL CHECK (length(command_bytes) <= 16384),
    native_command_digest TEXT NOT NULL,
    step_id TEXT NOT NULL,
    attempt INTEGER NOT NULL CHECK (attempt = 1),
    event_seq INTEGER NOT NULL CHECK (event_seq > 0),
    frozen_revision INTEGER NOT NULL CHECK (frozen_revision >= 0),
    bootstrap_event_seq INTEGER NOT NULL CHECK (bootstrap_event_seq > 0),
    PRIMARY KEY (owner_agent_id, run_id),
    UNIQUE (owner_agent_id, run_id, activation_id),
    FOREIGN KEY (owner_agent_id, run_id, definition_digest)
        REFERENCES taskflow_runs(owner_agent_id, run_id, definition_digest),
    FOREIGN KEY (owner_agent_id, run_id, step_id, attempt, event_seq)
        REFERENCES taskflow_step_outbox(owner_agent_id, run_id, step_id, attempt, event_seq)
);
CREATE TRIGGER qualification_choices_no_update
BEFORE UPDATE ON qualification_retrieval_choices BEGIN
    SELECT RAISE(ABORT, 'qualification choice is immutable');
END;
CREATE TRIGGER qualification_choices_no_delete
BEFORE DELETE ON qualification_retrieval_choices BEGIN
    SELECT RAISE(ABORT, 'qualification choice is immutable');
END;
CREATE TABLE qualification_retrieval_claims (
    owner_agent_id TEXT NOT NULL,
    run_id TEXT NOT NULL,
    activation_id TEXT NOT NULL,
    command_id TEXT NOT NULL,
    command_digest TEXT NOT NULL,
    command_bytes BLOB NOT NULL CHECK (length(command_bytes) <= 16384),
    native_command_digest TEXT NOT NULL,
    step_id TEXT NOT NULL,
    attempt INTEGER NOT NULL CHECK (attempt = 1),
    event_seq INTEGER NOT NULL CHECK (event_seq > 0),
    PRIMARY KEY (owner_agent_id, run_id, activation_id),
    FOREIGN KEY (owner_agent_id, run_id, activation_id)
        REFERENCES qualification_retrieval_choices(owner_agent_id, run_id, activation_id),
    FOREIGN KEY (owner_agent_id, run_id, step_id, attempt, event_seq)
        REFERENCES taskflow_step_outbox(owner_agent_id, run_id, step_id, attempt, event_seq)
);
CREATE TRIGGER qualification_claims_no_update
BEFORE UPDATE ON qualification_retrieval_claims BEGIN
    SELECT RAISE(ABORT, 'qualification claim is immutable');
END;
CREATE TRIGGER qualification_claims_no_delete
BEFORE DELETE ON qualification_retrieval_claims BEGIN
    SELECT RAISE(ABORT, 'qualification claim is immutable');
END;
