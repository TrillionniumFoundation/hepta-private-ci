-- Historical schema1..23 remains unchanged. This is preparation evidence,
-- never proof of physical provider contact or permission to send again.
CREATE TABLE taskflow_effect_preparation_evidence (
    owner_agent_id TEXT NOT NULL,
    run_id TEXT NOT NULL,
    step_id TEXT NOT NULL,
    attempt INTEGER NOT NULL CHECK (attempt > 0 AND attempt <= 1000000),
    record_json BLOB NOT NULL CHECK (length(record_json) BETWEEN 2 AND 32768),
    record_sha256 TEXT NOT NULL CHECK (
        length(record_sha256) = 64 AND record_sha256 NOT GLOB '*[^0-9a-f]*'
        AND record_sha256 != '0000000000000000000000000000000000000000000000000000000000000000'
    ),
    PRIMARY KEY(owner_agent_id, run_id, step_id, attempt),
    FOREIGN KEY(owner_agent_id, run_id, step_id, attempt)
        REFERENCES taskflow_effect_dispatch_attempts(owner_agent_id, run_id, step_id, attempt)
);

CREATE TRIGGER taskflow_effect_preparation_evidence_no_update
BEFORE UPDATE ON taskflow_effect_preparation_evidence
BEGIN
    SELECT RAISE(ABORT, 'TaskFlow preparation evidence is immutable');
END;
CREATE TRIGGER taskflow_effect_preparation_evidence_no_delete
BEFORE DELETE ON taskflow_effect_preparation_evidence
BEGIN
    SELECT RAISE(ABORT, 'TaskFlow preparation evidence is immutable');
END;

DROP TRIGGER automation_meta_no_update;
UPDATE automation_meta SET schema_version = 24 WHERE singleton = 1;
CREATE TRIGGER automation_meta_no_update
BEFORE UPDATE ON automation_meta
BEGIN
    SELECT RAISE(ABORT, 'automation owner metadata is immutable');
END;
