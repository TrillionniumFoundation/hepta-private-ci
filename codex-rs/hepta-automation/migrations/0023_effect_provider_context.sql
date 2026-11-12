-- Preserve historical effects without guessing their original provider target.
-- The current writer freezes transport context in the original dispatch row,
-- before the provider can be contacted. It never changes the operation key.
ALTER TABLE taskflow_effect_dispatch_attempts
    ADD COLUMN provider_context_sha256 TEXT
    CHECK (provider_context_sha256 IS NULL OR (
        length(provider_context_sha256) = 64
        AND provider_context_sha256 NOT GLOB '*[^0-9a-f]*'
        AND provider_context_sha256 != '0000000000000000000000000000000000000000000000000000000000000000'
    ));
ALTER TABLE taskflow_effect_dispatch_attempts
    ADD COLUMN provider_context_profile INTEGER NOT NULL DEFAULT 0
    CHECK (provider_context_profile IN (0, 1));
ALTER TABLE taskflow_effect_provider_bindings
    ADD COLUMN provider_context_profile INTEGER NOT NULL DEFAULT 0
    CHECK (provider_context_profile IN (0, 1));
ALTER TABLE taskflow_effect_dispatch_observations
    ADD COLUMN provider_context_profile INTEGER NOT NULL DEFAULT 0
    CHECK (provider_context_profile IN (0, 1));
ALTER TABLE taskflow_effect_dispatch_reconciliations
    ADD COLUMN provider_context_profile INTEGER NOT NULL DEFAULT 0
    CHECK (provider_context_profile IN (0, 1));

-- Fence new dispatch barriers and evidence appends from preopened old writers.
-- A dispatch already past its durable barrier still needs the owner use fence.
-- Explicit rowid collisions also bypass ordinary immutable DELETE triggers.
-- For implicit rowids, an undefined NEW.rowid can only cause conservative denial.
CREATE TRIGGER taskflow_effect_dispatch_attempts_require_context_profile
BEFORE INSERT ON taskflow_effect_dispatch_attempts
WHEN NEW.provider_context_profile != 1 OR EXISTS (
    SELECT 1 FROM taskflow_effect_dispatch_attempts WHERE rowid=NEW.rowid
) OR EXISTS (
    SELECT 1 FROM taskflow_effect_dispatch_attempts
    WHERE owner_agent_id=NEW.owner_agent_id
      AND ((run_id=NEW.run_id AND step_id=NEW.step_id AND attempt=NEW.attempt)
           OR grant_nonce_digest=NEW.grant_nonce_digest)
)
BEGIN
    SELECT RAISE(ABORT, 'TaskFlow effect requires the provider context writer');
END;

CREATE TRIGGER taskflow_effect_provider_bindings_require_context_profile
BEFORE INSERT ON taskflow_effect_provider_bindings
WHEN NEW.provider_context_profile != 1 OR EXISTS (
    SELECT 1 FROM taskflow_effect_provider_bindings WHERE rowid=NEW.rowid
) OR EXISTS (
    SELECT 1 FROM taskflow_effect_provider_bindings
    WHERE owner_agent_id=NEW.owner_agent_id AND run_id=NEW.run_id
      AND step_id=NEW.step_id
)
BEGIN
    SELECT RAISE(ABORT, 'TaskFlow effect requires the provider context writer');
END;

CREATE TRIGGER taskflow_effect_dispatch_observations_require_context_profile
BEFORE INSERT ON taskflow_effect_dispatch_observations
WHEN NEW.provider_context_profile != 1 OR EXISTS (
    SELECT 1 FROM taskflow_effect_dispatch_observations WHERE rowid=NEW.rowid
) OR EXISTS (
    SELECT 1 FROM taskflow_effect_dispatch_observations
    WHERE owner_agent_id=NEW.owner_agent_id AND run_id=NEW.run_id
      AND step_id=NEW.step_id AND attempt=NEW.attempt
)
BEGIN
    SELECT RAISE(ABORT, 'TaskFlow effect requires the provider context writer');
END;

CREATE TRIGGER taskflow_effect_dispatch_reconciliations_require_context_profile
BEFORE INSERT ON taskflow_effect_dispatch_reconciliations
WHEN NEW.provider_context_profile != 1 OR EXISTS (
    SELECT 1 FROM taskflow_effect_dispatch_reconciliations WHERE rowid=NEW.rowid
) OR EXISTS (
    SELECT 1 FROM taskflow_effect_dispatch_reconciliations
    WHERE owner_agent_id=NEW.owner_agent_id AND run_id=NEW.run_id
      AND step_id=NEW.step_id AND attempt=NEW.attempt
)
BEGIN
    SELECT RAISE(ABORT, 'TaskFlow effect requires the provider context writer');
END;

DROP TRIGGER automation_meta_no_update;
UPDATE automation_meta SET schema_version = 23 WHERE singleton = 1;
CREATE TRIGGER automation_meta_no_update
BEFORE UPDATE ON automation_meta
BEGIN
    SELECT RAISE(ABORT, 'automation owner metadata is immutable');
END;
