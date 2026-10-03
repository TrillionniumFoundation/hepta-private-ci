-- A legacy opaque receipt cannot prove that the provider never accepted.
ALTER TABLE taskflow_effect_dispatch_observations
ADD COLUMN provider_dispatch_status TEXT CHECK (
    provider_dispatch_status IS NULL
    OR (provider_dispatch_status IN ('unknown', 'accepted') AND observation = 'indeterminate')
    OR (provider_dispatch_status = 'completed' AND observation = 'succeeded')
    OR (provider_dispatch_status = 'rejected' AND observation = 'failed')
);

-- Status lookup may discover acceptance after an initially unknown dispatch.
-- Preserve the first such fact, bounded to one immutable row per attempt.
CREATE TABLE taskflow_effect_provider_acceptances (
    owner_agent_id TEXT NOT NULL,
    run_id TEXT NOT NULL,
    step_id TEXT NOT NULL,
    attempt INTEGER NOT NULL CHECK (attempt > 0 AND attempt <= 1000000),
    evidence_digest TEXT NOT NULL CHECK (
        length(evidence_digest) = 64 AND evidence_digest NOT GLOB '*[^0-9a-f]*'
        AND evidence_digest != '0000000000000000000000000000000000000000000000000000000000000000'
    ),
    observed_at_ms INTEGER NOT NULL CHECK (observed_at_ms >= 0),
    PRIMARY KEY(owner_agent_id, run_id, step_id, attempt),
    FOREIGN KEY(owner_agent_id, run_id, step_id, attempt)
        REFERENCES taskflow_effect_dispatch_attempts(owner_agent_id, run_id, step_id, attempt)
);

CREATE TRIGGER taskflow_effect_provider_acceptances_no_update
BEFORE UPDATE ON taskflow_effect_provider_acceptances
BEGIN
    SELECT RAISE(ABORT, 'TaskFlow provider acceptance is immutable');
END;
CREATE TRIGGER taskflow_effect_provider_acceptances_no_delete
BEFORE DELETE ON taskflow_effect_provider_acceptances
BEGIN
    SELECT RAISE(ABORT, 'TaskFlow provider acceptance is immutable');
END;

DROP TRIGGER automation_meta_no_update;
UPDATE automation_meta SET schema_version = 23 WHERE singleton = 1;
CREATE TRIGGER automation_meta_no_update
BEFORE UPDATE ON automation_meta
BEGIN
    SELECT RAISE(ABORT, 'automation owner metadata is immutable');
END;
