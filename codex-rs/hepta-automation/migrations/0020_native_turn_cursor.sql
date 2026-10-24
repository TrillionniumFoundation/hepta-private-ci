-- Native turn observations stay in the existing per-Agent TaskFlow store.
-- This table provides storage/CAS only, never execution authority.
CREATE TABLE taskflow_native_cursors (
    owner_agent_id TEXT NOT NULL,
    run_id TEXT NOT NULL,
    turn_key TEXT NOT NULL CHECK (length(turn_key) BETWEEN 1 AND 256),
    revision INTEGER NOT NULL CHECK (revision BETWEEN 1 AND 2048),
    previous_digest TEXT NOT NULL CHECK (typeof(previous_digest) = 'text' AND length(CAST(previous_digest AS BLOB)) = 64 AND previous_digest NOT GLOB '*[^0-9a-f]*'),
    evidence_digest TEXT NOT NULL CHECK (typeof(evidence_digest) = 'text' AND length(CAST(evidence_digest AS BLOB)) = 64 AND evidence_digest NOT GLOB '*[^0-9a-f]*'),
    encoded BLOB NOT NULL CHECK (typeof(encoded) = 'blob' AND length(encoded) BETWEEN 1 AND 4194304),
    PRIMARY KEY (owner_agent_id, run_id, turn_key, revision),
    FOREIGN KEY (owner_agent_id, run_id) REFERENCES taskflow_runs(owner_agent_id, run_id)
);
CREATE TRIGGER taskflow_native_cursors_no_update BEFORE UPDATE ON taskflow_native_cursors
BEGIN SELECT RAISE(ABORT, 'TaskFlow native cursors are immutable'); END;
CREATE TRIGGER taskflow_native_cursors_no_delete BEFORE DELETE ON taskflow_native_cursors
BEGIN SELECT RAISE(ABORT, 'TaskFlow native cursors are immutable'); END;
DROP TRIGGER automation_meta_no_update;
UPDATE automation_meta SET schema_version = 20 WHERE singleton = 1;
CREATE TRIGGER automation_meta_no_update BEFORE UPDATE ON automation_meta
BEGIN SELECT RAISE(ABORT, 'automation owner metadata is immutable'); END;
