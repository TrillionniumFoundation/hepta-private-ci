-- Completion and the exact original receipt/output are committed together.
CREATE TABLE circuit_v2_computation_transfers (
    owner_agent_id TEXT NOT NULL,
    run_id TEXT NOT NULL,
    activation_id INTEGER NOT NULL CHECK (activation_id >= 0),
    schema_id TEXT NOT NULL CHECK (
        typeof(schema_id) = 'text' AND length(CAST(schema_id AS BLOB)) BETWEEN 1 AND 128
    ),
    receipt_bytes BLOB NOT NULL CHECK (
        typeof(receipt_bytes) = 'blob' AND length(receipt_bytes) BETWEEN 1 AND 131072
    ),
    output_bytes BLOB NOT NULL CHECK (
        typeof(output_bytes) = 'blob' AND length(output_bytes) <= 65536
    ),
    PRIMARY KEY (owner_agent_id, run_id, activation_id),
    FOREIGN KEY (owner_agent_id, run_id) REFERENCES circuit_v2_runs(owner_agent_id, run_id)
);
CREATE TRIGGER circuit_v2_transfer_owner BEFORE INSERT ON circuit_v2_computation_transfers
WHEN NEW.owner_agent_id IS NOT (SELECT owner_agent_id FROM automation_meta WHERE singleton = 1)
BEGIN SELECT RAISE(ABORT, 'circuit transfer owner mismatch'); END;
CREATE TRIGGER circuit_v2_transfer_no_update BEFORE UPDATE ON circuit_v2_computation_transfers
BEGIN SELECT RAISE(ABORT, 'circuit computation transfers are immutable'); END;
CREATE TRIGGER circuit_v2_transfer_no_delete BEFORE DELETE ON circuit_v2_computation_transfers
BEGIN SELECT RAISE(ABORT, 'circuit computation transfers retain output and receipt history'); END;
DROP TRIGGER automation_meta_no_update;
UPDATE automation_meta SET schema_version = 22 WHERE singleton = 1;
CREATE TRIGGER automation_meta_no_update BEFORE UPDATE ON automation_meta
BEGIN SELECT RAISE(ABORT, 'automation owner metadata is immutable'); END;
