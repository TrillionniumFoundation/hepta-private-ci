-- Neural Circuit V2 is an additive owner-local execution layer.  It does not
-- change TaskFlow V1 rows or permit older decoders to consume V2 records.
DROP TRIGGER automation_meta_no_update;
UPDATE automation_meta SET schema_version = 20 WHERE singleton = 1 AND schema_version = 19;
CREATE TRIGGER automation_meta_no_update
BEFORE UPDATE ON automation_meta
BEGIN
    SELECT RAISE(ABORT, 'automation owner metadata is immutable');
END;

CREATE TABLE circuit_v2_definitions (
    owner_agent_id TEXT NOT NULL,
    circuit_id TEXT NOT NULL,
    version INTEGER NOT NULL CHECK (version > 0),
    definition_digest TEXT NOT NULL,
    definition_json TEXT NOT NULL,
    compatibility_source_digest TEXT,
    registered_at_ms INTEGER NOT NULL CHECK (registered_at_ms >= 0),
    PRIMARY KEY (owner_agent_id, circuit_id, version)
);

CREATE TABLE circuit_v2_runs (
    owner_agent_id TEXT NOT NULL,
    run_id TEXT NOT NULL,
    circuit_id TEXT NOT NULL,
    circuit_version INTEGER NOT NULL CHECK (circuit_version > 0),
    definition_digest TEXT NOT NULL,
    state TEXT NOT NULL CHECK (
        state IN ('queued', 'running', 'succeeded', 'failed', 'abstained', 'cancelled')
    ),
    next_activation_id INTEGER NOT NULL CHECK (next_activation_id > 0),
    max_rounds INTEGER NOT NULL CHECK (max_rounds > 0),
    max_activations INTEGER NOT NULL CHECK (max_activations > 0),
    fleet_lease_json TEXT NOT NULL,
    owner_id TEXT,
    owner_epoch INTEGER,
    generation INTEGER,
    fencing_token TEXT,
    lease_expires_at_ms INTEGER,
    created_at_ms INTEGER NOT NULL CHECK (created_at_ms >= 0),
    updated_at_ms INTEGER NOT NULL CHECK (updated_at_ms >= 0),
    PRIMARY KEY (owner_agent_id, run_id),
    FOREIGN KEY (owner_agent_id, circuit_id, circuit_version)
        REFERENCES circuit_v2_definitions(owner_agent_id, circuit_id, version),
    CHECK (
        (owner_id IS NULL AND owner_epoch IS NULL AND generation IS NULL
         AND fencing_token IS NULL AND lease_expires_at_ms IS NULL)
        OR
        (owner_id IS NOT NULL AND owner_epoch IS NOT NULL AND generation IS NOT NULL
         AND fencing_token IS NOT NULL AND lease_expires_at_ms IS NOT NULL)
    )
);

CREATE TABLE circuit_v2_activations (
    owner_agent_id TEXT NOT NULL,
    run_id TEXT NOT NULL,
    activation_id INTEGER NOT NULL CHECK (activation_id > 0),
    round INTEGER NOT NULL CHECK (round > 0),
    node_id TEXT NOT NULL,
    state TEXT NOT NULL CHECK (state IN ('ready', 'claimed', 'completed')),
    input_digest TEXT NOT NULL,
    predecessor_activation_id INTEGER,
    completion_id TEXT,
    completion_json TEXT,
    created_at_ms INTEGER NOT NULL CHECK (created_at_ms >= 0),
    updated_at_ms INTEGER NOT NULL CHECK (updated_at_ms >= 0),
    PRIMARY KEY (owner_agent_id, run_id, activation_id),
    UNIQUE (owner_agent_id, run_id, round, node_id),
    FOREIGN KEY (owner_agent_id, run_id)
        REFERENCES circuit_v2_runs(owner_agent_id, run_id)
);

CREATE INDEX circuit_v2_ready_idx
    ON circuit_v2_activations(owner_agent_id, run_id, state, round, activation_id);

CREATE INDEX circuit_v2_run_state_idx
    ON circuit_v2_runs(owner_agent_id, state, updated_at_ms, run_id);
