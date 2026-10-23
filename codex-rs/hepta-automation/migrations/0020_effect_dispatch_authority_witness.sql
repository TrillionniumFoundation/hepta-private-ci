-- Durable, non-authorizing authority evidence for the exact provider-entry cut.
-- The attempt row exists before final entry; this row is appended only after
-- kernel.authority revalidates the live grant and before provider contact.
CREATE TABLE taskflow_effect_dispatch_authority_witnesses (
    owner_agent_id TEXT NOT NULL,
    run_id TEXT NOT NULL,
    step_id TEXT NOT NULL,
    attempt INTEGER NOT NULL CHECK (attempt > 0 AND attempt <= 1000000),
    witness_json BLOB NOT NULL CHECK (
        length(witness_json) BETWEEN 2 AND 16384
    ),
    witness_sha256 TEXT NOT NULL CHECK (
        length(witness_sha256) = 64 AND witness_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    verified_at_unix_ms INTEGER NOT NULL CHECK (verified_at_unix_ms > 0),
    PRIMARY KEY(owner_agent_id, run_id, step_id, attempt),
    FOREIGN KEY(owner_agent_id, run_id, step_id, attempt)
        REFERENCES taskflow_effect_dispatch_attempts(
            owner_agent_id, run_id, step_id, attempt
        )
);

CREATE TRIGGER taskflow_effect_dispatch_authority_witnesses_no_update
BEFORE UPDATE ON taskflow_effect_dispatch_authority_witnesses
BEGIN
    SELECT RAISE(ABORT, 'TaskFlow effect authority witnesses are immutable');
END;
CREATE TRIGGER taskflow_effect_dispatch_authority_witnesses_no_delete
BEFORE DELETE ON taskflow_effect_dispatch_authority_witnesses
BEGIN
    SELECT RAISE(ABORT, 'TaskFlow effect authority witnesses are immutable');
END;

DROP TRIGGER automation_meta_no_update;
UPDATE automation_meta SET schema_version = 20 WHERE singleton = 1;
CREATE TRIGGER automation_meta_no_update
BEFORE UPDATE ON automation_meta
BEGIN
    SELECT RAISE(ABORT, 'automation owner metadata is immutable');
END;
