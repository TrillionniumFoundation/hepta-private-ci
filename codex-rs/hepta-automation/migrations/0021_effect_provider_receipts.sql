-- Structured provider receipts remain part of the existing TaskFlow effect
-- owner. There is one immutable first binding per original logical step and
-- at most one receipt on each of its existing observation/reconciliation rows.
-- Legacy rows retain NULL and never acquire invented provider history.
CREATE TABLE taskflow_effect_provider_bindings (
    owner_agent_id TEXT NOT NULL,
    run_id TEXT NOT NULL,
    step_id TEXT NOT NULL,
    attempt INTEGER NOT NULL CHECK (attempt > 0 AND attempt <= 1000000),
    receipt_json TEXT NOT NULL CHECK (
        typeof(receipt_json) = 'text' AND length(CAST(receipt_json AS BLOB)) BETWEEN 1 AND 1024
    ),
    receipt_digest TEXT NOT NULL CHECK (
        length(receipt_digest) = 64 AND receipt_digest NOT GLOB '*[^0-9a-f]*'
    ),
    observed_at_ms INTEGER NOT NULL CHECK (observed_at_ms >= 0),
    PRIMARY KEY(owner_agent_id, run_id, step_id),
    FOREIGN KEY(owner_agent_id, run_id, step_id, attempt)
        REFERENCES taskflow_effect_dispatch_attempts(owner_agent_id, run_id, step_id, attempt)
);

CREATE TRIGGER taskflow_effect_provider_bindings_no_update
BEFORE UPDATE ON taskflow_effect_provider_bindings
BEGIN
    SELECT RAISE(ABORT, 'TaskFlow provider operation bindings are immutable');
END;

CREATE TRIGGER taskflow_effect_provider_bindings_no_delete
BEFORE DELETE ON taskflow_effect_provider_bindings
BEGIN
    SELECT RAISE(ABORT, 'TaskFlow provider operation bindings are immutable');
END;

ALTER TABLE taskflow_effect_dispatch_observations
    ADD COLUMN provider_receipt_json TEXT CHECK (
        provider_receipt_json IS NULL OR (
            typeof(provider_receipt_json) = 'text'
            AND length(CAST(provider_receipt_json AS BLOB)) BETWEEN 1 AND 1024
        )
    );

ALTER TABLE taskflow_effect_dispatch_reconciliations
    ADD COLUMN provider_receipt_json TEXT CHECK (
        provider_receipt_json IS NULL OR (
            typeof(provider_receipt_json) = 'text'
            AND length(CAST(provider_receipt_json AS BLOB)) BETWEEN 1 AND 1024
        )
    );

DROP TRIGGER automation_meta_no_update;
UPDATE automation_meta SET schema_version = 21 WHERE singleton = 1;
CREATE TRIGGER automation_meta_no_update
BEFORE UPDATE ON automation_meta
BEGIN
    SELECT RAISE(ABORT, 'automation owner metadata is immutable');
END;
