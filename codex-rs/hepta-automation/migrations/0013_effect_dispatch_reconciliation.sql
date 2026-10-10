-- A provider may first return an indeterminate observation and later supply a
-- terminal reconciliation for the same immutable dispatch identity. Preserve
-- both facts append-only; the reconciliation row never authorizes redispatch.
CREATE TABLE taskflow_effect_dispatch_reconciliations (
    owner_agent_id TEXT NOT NULL,
    run_id TEXT NOT NULL,
    step_id TEXT NOT NULL,
    attempt INTEGER NOT NULL CHECK (attempt > 0 AND attempt <= 1000000),
    observation TEXT NOT NULL CHECK (
        observation IN ('proven_absent', 'succeeded', 'failed')
    ),
    evidence_digest TEXT NOT NULL CHECK (
        length(evidence_digest) = 64 AND evidence_digest NOT GLOB '*[^0-9a-f]*'
    ),
    observed_at_ms INTEGER NOT NULL CHECK (observed_at_ms >= 0),
    PRIMARY KEY(owner_agent_id, run_id, step_id, attempt),
    FOREIGN KEY(owner_agent_id, run_id, step_id, attempt)
        REFERENCES taskflow_effect_dispatch_attempts(
            owner_agent_id, run_id, step_id, attempt
        )
);

CREATE TRIGGER taskflow_effect_dispatch_reconciliations_no_update
BEFORE UPDATE ON taskflow_effect_dispatch_reconciliations
BEGIN
    SELECT RAISE(ABORT, 'TaskFlow effect reconciliations are immutable');
END;

CREATE TRIGGER taskflow_effect_dispatch_reconciliations_no_delete
BEFORE DELETE ON taskflow_effect_dispatch_reconciliations
BEGIN
    SELECT RAISE(ABORT, 'TaskFlow effect reconciliations are immutable');
END;

DROP TRIGGER automation_meta_no_update;
UPDATE automation_meta SET schema_version = 13 WHERE singleton = 1;
CREATE TRIGGER automation_meta_no_update
BEFORE UPDATE ON automation_meta
BEGIN
    SELECT RAISE(ABORT, 'automation owner metadata is immutable');
END;
