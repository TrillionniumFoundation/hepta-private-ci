-- Original downstream bytes are committed with the claim, never reconstructed
-- from a retry. The corresponding versioned event binds their canonical digest.
CREATE TABLE circuit_v2_computation_inputs (
    owner_agent_id TEXT NOT NULL,
    run_id TEXT NOT NULL,
    activation_id INTEGER NOT NULL CHECK (activation_id >= 0),
    schema_id TEXT NOT NULL CHECK (
        typeof(schema_id) = 'text' AND length(CAST(schema_id AS BLOB)) BETWEEN 1 AND 128
    ),
    input_bytes BLOB NOT NULL CHECK (
        typeof(input_bytes) = 'blob' AND length(input_bytes) BETWEEN 1 AND 65536
    ),
    PRIMARY KEY (owner_agent_id, run_id, activation_id),
    FOREIGN KEY (owner_agent_id, run_id)
        REFERENCES circuit_v2_runs(owner_agent_id, run_id)
);
CREATE TRIGGER circuit_v2_input_owner BEFORE INSERT ON circuit_v2_computation_inputs
WHEN NEW.owner_agent_id IS NOT (SELECT owner_agent_id FROM automation_meta WHERE singleton = 1)
BEGIN SELECT RAISE(ABORT, 'circuit input owner mismatch'); END;
CREATE TRIGGER circuit_v2_input_no_update BEFORE UPDATE ON circuit_v2_computation_inputs
BEGIN SELECT RAISE(ABORT, 'circuit computation inputs are immutable'); END;
CREATE TRIGGER circuit_v2_input_no_delete BEFORE DELETE ON circuit_v2_computation_inputs
BEGIN SELECT RAISE(ABORT, 'circuit computation inputs retain unresolved work and history'); END;
DROP TRIGGER automation_meta_no_update;
UPDATE automation_meta SET schema_version = 21 WHERE singleton = 1;
CREATE TRIGGER automation_meta_no_update BEFORE UPDATE ON automation_meta
BEGIN SELECT RAISE(ABORT, 'automation owner metadata is immutable'); END;
