-- Durable provider-contact boundary for final-use-authorized TaskFlow effects.
-- The start row is immutable evidence that external dispatch may have happened.
-- The observation row is separately immutable so a crash between provider
-- return and TaskFlow projection update can be repaired without redispatch.
CREATE TABLE taskflow_effect_dispatch_attempts (
    owner_agent_id TEXT NOT NULL,
    run_id TEXT NOT NULL,
    step_id TEXT NOT NULL,
    attempt INTEGER NOT NULL CHECK (attempt > 0 AND attempt <= 1000000),
    intent_digest TEXT NOT NULL CHECK (
        length(intent_digest) = 64 AND intent_digest NOT GLOB '*[^0-9a-f]*'
    ),
    payload_digest TEXT NOT NULL CHECK (
        length(payload_digest) = 64 AND payload_digest NOT GLOB '*[^0-9a-f]*'
    ),
    binding_digest TEXT NOT NULL CHECK (
        length(binding_digest) = 64 AND binding_digest NOT GLOB '*[^0-9a-f]*'
    ),
    destination_id TEXT NOT NULL CHECK (length(destination_id) BETWEEN 1 AND 128),
    authority_epoch INTEGER NOT NULL CHECK (authority_epoch > 0),
    grant_id TEXT NOT NULL CHECK (length(grant_id) BETWEEN 1 AND 128),
    grant_nonce_digest TEXT NOT NULL CHECK (
        length(grant_nonce_digest) = 64 AND grant_nonce_digest NOT GLOB '*[^0-9a-f]*'
    ),
    record_command_id TEXT NOT NULL CHECK (length(record_command_id) BETWEEN 1 AND 256),
    started_at_ms INTEGER NOT NULL CHECK (started_at_ms >= 0),
    PRIMARY KEY(owner_agent_id, run_id, step_id, attempt),
    UNIQUE(owner_agent_id, grant_nonce_digest),
    FOREIGN KEY(owner_agent_id, run_id)
        REFERENCES taskflow_runs(owner_agent_id, run_id)
);

CREATE TABLE taskflow_effect_dispatch_observations (
    owner_agent_id TEXT NOT NULL,
    run_id TEXT NOT NULL,
    step_id TEXT NOT NULL,
    attempt INTEGER NOT NULL CHECK (attempt > 0 AND attempt <= 1000000),
    observation TEXT NOT NULL CHECK (
        observation IN ('proven_absent', 'succeeded', 'failed', 'indeterminate')
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

CREATE TRIGGER taskflow_effect_dispatch_attempts_no_update
BEFORE UPDATE ON taskflow_effect_dispatch_attempts
BEGIN
    SELECT RAISE(ABORT, 'TaskFlow effect dispatch attempts are immutable');
END;

CREATE TRIGGER taskflow_effect_dispatch_attempts_no_delete
BEFORE DELETE ON taskflow_effect_dispatch_attempts
BEGIN
    SELECT RAISE(ABORT, 'TaskFlow effect dispatch attempts are immutable');
END;

CREATE TRIGGER taskflow_effect_dispatch_observations_no_update
BEFORE UPDATE ON taskflow_effect_dispatch_observations
BEGIN
    SELECT RAISE(ABORT, 'TaskFlow effect dispatch observations are immutable');
END;

CREATE TRIGGER taskflow_effect_dispatch_observations_no_delete
BEFORE DELETE ON taskflow_effect_dispatch_observations
BEGIN
    SELECT RAISE(ABORT, 'TaskFlow effect dispatch observations are immutable');
END;

DROP TRIGGER automation_meta_no_update;
UPDATE automation_meta SET schema_version = 11 WHERE singleton = 1;
CREATE TRIGGER automation_meta_no_update
BEFORE UPDATE ON automation_meta
BEGIN
    SELECT RAISE(ABORT, 'automation owner metadata is immutable');
END;
